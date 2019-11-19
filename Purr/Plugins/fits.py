# -*- coding: utf-8 -*-
# PIL is show-stoppers for this plugin
try:
    import PIL.Image
except:
    # image.py will complain about this one too, more verbosely
    print("""Python Imaging Library (PIL) not found, rendering of FITS files will not be available.
PIL can be installed from the Debian/Ubuntu package python-imaging, or can be downloaded from
http://www.pythonware.com/index.htm.
""")
    raise

try:
    from astropy.io import fits
except:
    print("""astropy package not found, rendering of FITS files will not be available.
""")
    raise

try:
    import numpy
    import scipy.ndimage.measurements
except:
    print("""numpy and/or scipy packages not found, rendering of FITS files will not be available.
Numpy and scipy can be installed from Debian/Ubuntu packages python-numpy and python-scipy, or can
be downloaded from http://numpy.scipy.org.
""")
    raise

# pychart needed for rendering histograms, but we can get on without it
from .local_pychart import *

pychart = True

# except:
#  pychart = None
#  print """PyChart package not found, rendering of FITS histograms will not be available.
# PyChart is available from http://home.gna.org/pychart/, or as Debian package python-pychart.
# """

import os.path
import traceback
import math
import pickle
import time

import Purr
from Purr.Render import quote_url, dprint, dprintf
from Purr.CachingRenderer import CachingRenderer
import Kittens.utils


class FITSRenderer(CachingRenderer):
    """This class renders FITS image data products."""

    @staticmethod
    def canRender(filename):
        """We can render it if PIL can read it."""
        if filename.endswith(".fits") or filename.endswith(".FITS"):
            return 10
        return False

    # this gives a short ID for the class (used in GUIs and such)
    renderer_id = "fits"

    # this gives a documentation string. You can use rich text here
    renderer_doc = """<P>The "fits" plugin provides rendering of FITS images."""

    # maximum thumbnail width & height
    # define renderer options
    CachingRenderer.addOption("image-thumbnail-width", 512, dtype=int, doc="Maximum width of thumbnails")
    CachingRenderer.addOption("image-thumbnail-height", 256, dtype=int, doc="Maximum height of thumbnails")
    CachingRenderer.addOption("hist-width", 1024, dtype=int, doc="Width of histogram plot")
    CachingRenderer.addOption("hist-height", 1024, dtype=int, doc="Height of histogram plot")
    CachingRenderer.addOption("hist-thumbnail-width", 128, dtype=int, doc="Maximum width of thumbnails")
    CachingRenderer.addOption("hist-thumbnail-height", 128, dtype=int, doc="Maximum height of thumbnails")
    CachingRenderer.addOption("fits-nimage", 4, dtype=int,
                              doc="Maximum number of planes to include, when dealing with cubes")
    CachingRenderer.addOption("fits-hist-nbin", 512, dtype=int, doc="Number of bins to use when making histograms""")
    CachingRenderer.addOption("fits-hist-clip", .95, dtype=float, doc="Apply histogram clipping")

    def _renderCacheFile(self, cachetype, relpath):
        return ("-cache-%s-rel-%s.html" % (cachetype, bool(relpath))).lower()

    @staticmethod
    def compute_tics(x0, x1):
        # work out tic interval
        dx = x1 - x0
        tic = 10 ** math.floor(math.log10(dx))
        if dx / tic < 2:
            tic /= 5
        elif dx / tic < 5:
            tic /= 2
        # work out where the tics are (in terms of i*interval)
        it0 = int(math.floor(x0 / tic))
        it1 = int(math.floor(x1 / tic))
        if it0 * tic < x0:
            it0 += 1
        # scale back up and return
        return [i * tic for i in range(it0, it1 + 1)]

    def _make_histogram(self, path, title, x, y):
        # make histogram by doubling up each x point to make "horizontals"
        x = list(map(float, x))
        y = list(map(int, y))
        width = x[1] - x[0]
        xy = []
        for a, b in zip(x, y):
            xy += [(a, b), (a + width, b)]
        # Make sure all spaces in path are escaped as pychart cannot handle them
        path = path.replace('\ ', ' ').replace(' ', '\ ')
        canv = canvas.init(path)
        ar = area.T(
            x_axis=axis.X(label="/20{}" + title, format="/20{}%g", tic_interval=self.compute_tics),
            y_axis=axis.Y(label=None, format="/20{}%s"),
            x_grid_style=line_style.gray70,
            y_grid_style=line_style.gray70,
            legend=None,
            size=self.hist_size
        )
        ar.add_plot(line_plot.T(
            data=xy, xcol=0, ycol=1,
            line_style=line_style.black,
            label=None,
            data_label_format=None
        ))
        ar.draw(canv)
        canv.close()

    def regenerate(self):
        Purr.progressMessage("reading %s" % self.dp.filename, sub=True)
        # init fitsfile to None, so that _read() above is forced to re-read it
        fitsfile = fits.open(self.dp.fullpath)
        header = fitsfile[0].header

        dprintf(3, "beginning render of", self.dp.fullpath);
        t0 = time.time()
        # write out FITS header
        self.headerfile, path, uptodate = self.subproduct("-fitsheader.html")
        if not uptodate:
            title = "FITS header for %s" % self.dp.filename
            html = """<HTML><BODY><TITLE>%s</TITLE>
      <H2>%s</H2>
      <PRE>""" % (title, title)
            for line in header.ascard:
                line = str(line).replace("<", "&lt;").replace(">", "&gt;")
                html += line + "\n"
            html += """
      </PRE></BODY></HTML>\n"""
            try:
                open(path, "w").write(html)
            except:
                print(("Error writing file %s" % path))
                traceback.print_exc()
                self.headerfile = None

        # figure out number of images to include
        ndim = header['NAXIS']
        fitsshape = [header['NAXIS%d' % i] for i in range(1, ndim + 1)]
        self.cubesize = 'x'.join(map(str, fitsshape))
        if ndim < 2:
            raise TypeError("can't render one-dimensional FITS files""")
        elif ndim == 2:
            fitsdata_to_images = lambda fdata: [fdata]
            nplanes = 1
        else:
            ax1 = ax2 = None
            # find the X/Y axes, by looking at CTYPEx
            # note that the array axes are in reverse order. I.e. if X is FITS axis 1 and Y is axis 2,
            # the array will be of e.g. shape 1,1,NY,NX, while fitsshape is [NX,NY,1,1]
            for i in range(1, ndim + 1):
                ctype = header['CTYPE%d' % i]
                if [prefix for prefix in ("RA", "GLON", "ELON", "HLON", "SLON") if ctype.startswith(prefix)] \
                        or ctype in ("L", "X"):
                    ax1 = ndim - i
                elif [prefix for prefix in ("DEC", "GLAT", "ELAT", "HLAT", "SLAT") if ctype.startswith(prefix)] \
                        or ctype in ("M", "Y"):
                    ax2 = ndim - i
            if ax1 is None or ax2 is None:
                ax1, ax2 = 1, 0
            arrshape = fitsshape[-1::-1]
            # this is how many planes we render, at most
            nplanes = max(self.getOption('fits-nimage'), 1)
            slices = []
            baseslice = [0] * ndim
            baseslice[ax1] = baseslice[ax2] = None
            imgshape = (arrshape[min(ax1, ax2)], arrshape[max(ax1, ax2)])
            while len(slices) < nplanes:
                slices.append(tuple(baseslice))
                for idim in range(ndim):
                    if baseslice[idim] != None:
                        baseslice[idim] += 1
                        if baseslice[idim] < arrshape[idim]:
                            break
                        else:
                            baseslice[idim] = 0
                else:
                    break
            nplanes = len(slices)

            # OK, slices contains how many slices to return
            def fitsdata_to_images(fdata, slices=slices, imgshape=imgshape):
                dprint(3, "fitsdata_to_images", slices, fdata.shape);
                t0 = time.time()
                # reshape to collapse into a 3D cube
                img = [fdata[i].reshape(imgshape) for i in slices]
                dprint(3, "collecting images took", time.time() - t0, "secs");
                t0 = time.time()
                return img

        # OK, now cycle over all images
        dprintf(3, "%s: rendering %d planes\n", self.dp.fullpath, nplanes);
        t0 = time.time()

        self.imgrec = [None] * nplanes
        # get number of bins (0 or None means no histogram)
        nbins = self.getOption("fits-hist-nbin")
        # see if histogram clipping is enabled, set hclip to None if not
        self.hclip = hclip = self.getOption("fits-hist-clip")
        if hclip == 1 or not nbins:
            hclip = None

        tsize_img = self.getOption("image-thumbnail-width"), self.getOption("image-thumbnail-height")
        tsize_hist = self.getOption("hist-thumbnail-width"), self.getOption("hist-thumbnail-height")
        self.hist_size = self.getOption("hist-width"), self.getOption("hist-height")

        # filled once we read the data
        images = None

        for num_image in range(nplanes):
            # do we have a cached status record for this image?
            recfile, recpath, uptodate = self.subproduct("-%d-stats" % num_image)
            if uptodate:
                dprintf(3, "%s(%d): stats file %s up-to-date, reading in\n", self.dp.fullpath, num_image, recfile)
                try:
                    self.imgrec[num_image] = pickle.load(open(recpath, "rb"))
                    continue
                except:
                    print(("Error reading stats file %s, regenerating everything" % recpath))
                    traceback.print_exc()
            # out of date, so we regenerate everything
            # build up record of stuff associated with this image
            rec = self.imgrec[num_image] = Kittens.utils.recdict()

            # generate paths for images
            rec.fullimage, img_path = self.subproductPath("-%d-full.png" % num_image)
            rec.thumbnail, img_thumb = self.subproductPath("-%d-thumb.png" % num_image)
            if pychart:
                rec.histogram_full, hf_path = self.subproductPath("-%d-hist-full.png" % num_image)
                rec.histogram_zoom, hz_path = self.subproductPath("-%d-hist-zoom.png" % num_image)
                rec.histogram_full_thumb, hf_thumb = self.subproductPath("-%d-hist-full-thumb.png" % num_image)
                rec.histogram_zoom_thumb, hz_thumb = self.subproductPath("-%d-hist-zoom-thumb.png" % num_image)

            # need to read in data at last
            if not images:
                dprint(3, "reading data");
                t0 = time.time()
                fitsdata = fitsfile[0].data
                dprint(3, "reading data took", time.time() - t0, "secs");
                t0 = time.time()
                fitsfile = None
                images = fitsdata_to_images(fitsdata)
                dprint(3, "converting to images took", time.time() - t0, "secs");
                t0 = time.time()
                fitsdata = None

            data = images[num_image]

            title = self.dp.filename
            if nplanes > 1:
                title += ", plane #%d" % num_image
            Purr.progressMessage("rendering %s" % title, sub=True)

            # min/max data values
            dprint(3, "rendering plane", num_image);
            t0 = time.time()
            datamask = ~numpy.isfinite(data)
            dprint(3, "making mask took", time.time() - t0, "secs");
            t0 = time.time()
            datamin, datamax = scipy.ndimage.measurements.extrema(data, datamask, False)[:2]
            dprint(3, "computing min/max took", time.time() - t0, "secs");
            t0 = time.time()
            rec.datamin, rec.datamax = datamin, datamax
            # mean and sigma
            rec.datamean = scipy.ndimage.measurements.mean(data, datamask, False)
            dprint(3, "computing mean took", time.time() - t0, "secs");
            t0 = time.time()
            rec.datastd = scipy.ndimage.measurements.standard_deviation(data, datamask, False)
            dprint(3, "computing std took", time.time() - t0, "secs");
            t0 = time.time()
            # thumbnail files will be "" if images are small enough to be inlined.
            # these will be None if no histogram clipping is applied
            rec.clipmin, rec.clipmax = None, None
            dprintf(3, "%s plane %d: datamin %g, datamax %g\n", self.dp.fullpath, num_image, rec.datamin, rec.datamax)
            # compute histogram of data only if this is enabled,
            # and either pychart is available (so we can produce plots), or histogram clipping is in effect
            if datamin != datamax and nbins and (pychart or hclip):
                dprintf(3, "%s plane %d: computing histogram\n", self.dp.fullpath, num_image)
                counts = scipy.ndimage.measurements.histogram(data, datamin, datamax, nbins, labels=datamask,
                                                              index=False);  # needed for 1.3+ to avoid warnings
                edges = datamin + (datamax - datamin) * (numpy.arange(nbins, dtype=float) + .5) / nbins
                dprint(3, "computing histogram took", time.time() - t0, "secs");
                t0 = time.time()
                # render histogram
                if pychart:
                    try:
                        self._make_histogram(hf_path, "Histogram of %s" % title, edges, counts)
                        dprint(3, "rendering histogram took", time.time() - t0, "secs");
                        t0 = time.time()
                    except:
                        print(("Error rendering histogram %s" % hf_path))
                        traceback.print_exc()
                        rec.histogram_full = None
                    # if histogram was rendered, make a thumbnail
                    if rec.histogram_full:
                        self.makeThumb(hf_path, hf_thumb, tsize_hist)
                    else:
                        rec.histogram_full_thumb = None
                # now, compute clipped data if needed
                if hclip:
                    # find max point in histogram
                    ic = counts.argmax()
                    # compute number of points that need to be included, given the clip factor
                    target_count = int(data.size * hclip)
                    ih0 = ih1 = ic
                    totcount = counts[ic]
                    # find how many bins to include around ic, stopping when we hit the edge
                    while totcount < target_count:
                        if ih0 > 0:
                            ih0 -= 1
                            totcount += counts[ih0]
                        if ih1 < nbins - 1:
                            ih1 += 1
                            totcount += counts[ih1]
                        # just in case
                        if ih0 <= 0 and ih1 >= nbins - 1:
                            break
                    # and these are the clipping limits
                    datamin = float(edges[ih0])
                    if ih1 >= nbins - 1:
                        ih1 = nbins - 1;  # and datamax is already the clipping limit
                    else:
                        ih1 += 1
                        datamax = float(edges[ih1])
                    rec.clipmin, rec.clipmax = datamin, datamax
                    dprintf(3, "%s plane %d: clipping to %g,%g\n", self.dp.fullpath, num_image, rec.clipmin,
                            rec.clipmax)
                    # render zoomed histogram
                    if pychart:
                        if rec.clipmax != rec.clipmin:
                            zcounts = scipy.ndimage.measurements.histogram(data, rec.clipmin, rec.clipmax, nbins,
                                                                           labels=datamask,
                                                                           index=False);  # needed for 1.3+ to avoid warnings
                            zedges = rec.clipmin + (rec.clipmax - rec.clipmin) * (
                                        numpy.arange(nbins, dtype=float) + .5) / nbins
                            try:
                                self._make_histogram(hz_path, "Histogram zoom of %s" % title, zedges, zcounts)
                                dprint(3, "rendering zoomed histogram took", time.time() - t0, "secs");
                                t0 = time.time()
                            except:
                                print(("Error rendering histogram %s" % hz_path))
                                traceback.print_exc()
                                rec.histogram_zoom = None
                        else:  # no meaningful zoomed area to render
                            rec.histogram_zoom = None
                        # if histogram was rendered, make a thumbnail
                        if rec.histogram_zoom:
                            histogram_zoom_thumb = self.makeThumb(hz_path, hz_thumb, tsize_hist)
                        else:
                            rec.histogram_zoom_thumb = None
                    # clip data
                    data = numpy.clip(data, datamin, datamax)
                # end of clipping
            # else no histogram for whatever reason
            else:
                rec.histogram_full = rec.histogram_zoom = rec.histogram_full_thumb = rec.histogram_zoom_thumb = None
            # ok, data has been clipped if need be. Rescale it to 8-bit integers
            t0 = time.time()
            datarng = datamax - datamin
            if datarng:
                data = (data - datamin) * (255 / datarng)
                data = data.round().astype('uint8')
                data[datamask] = 255
            else:
                data = numpy.zeros(data.shape, dtype='uint8')
            dprintf(3, "%s plane %d: rescaled to %d:%d in %f seconds\n", self.dp.fullpath, num_image, data.min(),
                    data.max(), time.time() - t0);
            t0 = time.time()
            # generate PNG image
            img = None
            try:
                img = PIL.Image.frombuffer('L', data.shape[-1::-1], numpy.getbuffer(data), "raw", 'L', 0, -1)
                dprint(3, "image frombuffer took", time.time() - t0, "secs");
                t0 = time.time()
                # img = PIL.Image.new('L',data.shape)
                # dprint(3,"new image took",time.time()-t0,"secs"); t0 = time.time()
                # imgdata = data.reshape((data.size,))
                # dprint(3,"data.reshape took",time.time()-t0,"secs"); t0 = time.time()
                # img.putdata(imgdata)
                # dprint(3,"putdata took",time.time()-t0,"secs"); t0 = time.time()
                # img = img.transpose(PIL.Image.FLIP_TOP_BOTTOM)
                # dprint(3,"transpose took",time.time()-t0,"secs"); t0 = time.time()
                img.save(img_path, 'PNG')
                dprint(3, "saving took", time.time() - t0, "secs");
                t0 = time.time()
            except:
                print(("Error rendering image %s" % path))
                traceback.print_exc()
                rec.fullimage = img = None
            # if image was rendered, make a thumbnail
            if rec.fullimage:
                thumb = self.makeThumb(img_path, img_thumb, tsize_img, img=img)
                dprint(3, "rendering thumbnail took", time.time() - t0, "secs");
                t0 = time.time()
                # None means thumbnail failed
                if thumb is None:
                    rec.thumbnail = None
                # else perhaps image is its own thumbnail
                elif thumb is img_path:
                    rec.thumbnail = rec.fullimage
            else:
                rec.thumbnail = None
            # write stats
            try:
                pickle.dump(rec, open(recpath, 'rw'))
            except:
                print(("Error writing stats file  %s" % recpath))
                traceback.print_exc()

    def makeThumb(self, imagepath, thumbpath, tsize, img=None):
        """makes a thumbnail for the given image.
        imagepath refers to an image file
        img can be an open PIL.Image -- if None, then imagepath is opened
        tsize is a width,height tuple giving the max thumbnail size
        extension is the extension of the thumbnail file
        """
        try:
            # open image if needed
            if not img:
                img = PIL.Image.open(imagepath)
            # do we need a thumbnail at all, or can the image be inlined?
            width, height = img.size
            factor = max(width / float(tsize[0]), height / float(tsize[1]))
            if factor <= 1:
                return imagepath
            # generate the thumbnail
            img = img.resize((int(width / factor), int(height / factor)), PIL.Image.ANTIALIAS)
            img.save(thumbpath, "PNG")
            return thumbpath
        except:
            print(("Error rendering thumbnail %s" % thumbpath))
            traceback.print_exc()
            return None

    def _renderSingleImage(self, image, thumb, relpath):
        if image is None:
            return ""
        # else no thumbnail: make "image" link
        elif thumb is None:
            fname = relpath + image
            return """<A HREF="%s">image</A>""" % quote_url(fname)
        # else return thumbnail linking to full image
        else:
            tname = relpath + thumb
            fname = relpath + image
            return """<A HREF="%s"><IMG SRC="%s" ALT="%s"></A>""" % (quote_url(fname), quote_url(tname),
                                                                     quote_url(os.path.basename(image)))

    def _renderImageRec(self, rec, relpath, include_size=False):
        # get HTML code for image and histograms
        html_image = self._renderSingleImage(rec.fullimage, rec.thumbnail, relpath)
        if rec.histogram_full:
            html_hist_full = self._renderSingleImage(rec.histogram_full, rec.histogram_full_thumb, relpath)
        else:
            html_hist_full = ""
        if rec.histogram_zoom:
            html_hist_zoom = self._renderSingleImage(rec.histogram_zoom, rec.histogram_zoom_thumb, relpath)
        else:
            html_hist_zoom = ""
        # arrange images side-by-side
        html_img = "<TABLE><TR><TD ROWSPAN=2>%s</TD><TD>%s</TD></TR><TR><TD>%s</TD></TR></TABLE>" % \
                   (html_image, html_hist_full, html_hist_zoom)
        # form up comments
        html_cmt = """<TABLE><TR><TD>data range:</TD><TD>%g,%g</TD></TR>""" % (rec.datamin, rec.datamax)
        if include_size:
            html_cmt += """
         <TR><TD>size:</TD><TD>%s</TD></TR>\n""" % self.cubesize
        html_cmt += """
         <TR><TD>mean:</TD><TD>%g</TD></TR>
         <TR><TD>sigma:</TD><TD>%g</TD></TR>""" % (rec.datamean, rec.datastd)
        if rec.clipmin is not None:
            html_cmt += """
         <TR><TD>clipping:</TD><TD>%g%%</TD></TR>
         <TR><TD>clip range:</TD><TD>%g,%g</TD></TR>""" % (self.hclip * 100, rec.clipmin, rec.clipmax)
        html_cmt += """\n
       </TABLE>"""
        return html_img, html_cmt

    def renderLink(self, relpath=""):
        """renderLink() is called to render a link to the DP
        """
        # return from cache if available
        cachekey, html = self.checkCache('Link', relpath)
        if html is not None:
            return html
        # else regenerate
        html = CachingRenderer.renderLink(self, relpath)
        if self.headerfile is not None:
            html += """ (<A HREF="%s">header</A>)""" % quote_url(relpath + self.headerfile)
        # save to cache
        return self.writeCache(cachekey, html)

    def renderInTable(self, relpath=""):
        """renderInTable() is called to render FITS images in a table"""
        # return from cache if available
        cachekey, html = self.checkCache('InTable', relpath)
        if html is not None:
            return html
        # else regenerate
        # single image: render as standard cells
        if len(self.imgrec) == 1:
            rec = self.imgrec[0]
            # add header
            html = "    <TR><TD COLSPAN=2>"
            html += self.renderLinkComment(relpath) or ""
            html += "</TD></TR>\n"
            html_img, comment = self._renderImageRec(rec, relpath, include_size=True)
            html += "\n".join([
                "    <TR>",
                "      <TD>%s</TD>" % html_img,
                "      <TD>%s</TD>" % comment,
                "    </TR>\n"])
        # multiple images: render a single header row, followed by one row per image
        else:
            # add header
            html = "    <TR><TD COLSPAN=2>"
            html += self.renderLinkComment(relpath)
            # append information on image and end the table row
            html += "\n      <DIV ALIGN=right><P>%s FITS cube, %d planes are given below.</P></DIV></TD></TR>\n" % (
            self.cubesize, len(self.imgrec))
            # now loop over images and generate a table row for each
            for irec, rec in enumerate(self.imgrec):
                html_img, comment = self._renderImageRec(rec, relpath)
                comment = "<P>Image plane #%d.</P>%s" % (irec, comment)
                html += "\n".join([
                    "    <TR>",
                    "      <TD>%s</TD>" % html_img,
                    "      <TD>%s</TD>" % comment,
                    "    </TR>\n"])
        return self.writeCache(cachekey, html)

    def renderThumbnail(self, relpath=""):
        """renderThumbnail() is called to render a thumbnail of the DP.
        We only render the first image (in case of multiple images)
        """
        # return from cache if available
        cachekey, html = self.checkCache('Thumbnail', relpath)
        if html is not None:
            return html
        # else regenerate
        rec = self.imgrec[0]
        html = self._renderSingleImage(rec.fullimage, rec.thumbnail, relpath)
        # save to cache
        return self.writeCache(cachekey, html)


# register ourselves with Purr
import Purr.Render

Purr.Render.addRenderer(FITSRenderer, __name__, __file__)
