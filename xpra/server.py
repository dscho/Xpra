# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Todo:
#   xsync resize stuff
#   shape?
#   any other interesting metadata? _NET_WM_TYPE, WM_TRANSIENT_FOR, etc.?

import gtk.gdk
gtk.gdk.threads_init()

import gobject
import cairo
import sys
import hmac
import uuid
import StringIO
import os
from collections import deque
import time
import ctypes
from threading import Thread
import Queue
from math import log as mathlog
from math import sqrt
def logp2(x):
    return mathlog(1+x, 2)

from wimpiggy.wm import Wm
from wimpiggy.util import (AdHocStruct,
                           one_arg_signal,
                           gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)
from wimpiggy.lowlevel import (get_rectangle_from_region,   #@UnresolvedImport
                               xtest_fake_key,              #@UnresolvedImport
                               xtest_fake_button,           #@UnresolvedImport
                               set_key_repeat_rate,         #@UnresolvedImport
                               ungrab_all_keys,             #@UnresolvedImport
                               unpress_all_keys,            #@UnresolvedImport
                               is_override_redirect,        #@UnresolvedImport
                               is_mapped,                   #@UnresolvedImport
                               add_event_receiver,          #@UnresolvedImport
                               get_cursor_image,            #@UnresolvedImport
                               get_children,                #@UnresolvedImport
                               has_randr, get_screen_sizes, #@UnresolvedImport
                               set_screen_size,             #@UnresolvedImport
                               get_screen_size)             #@UnresolvedImport
from wimpiggy.prop import prop_set
from wimpiggy.window import OverrideRedirectWindowModel, Unmanageable
from wimpiggy.keys import grok_modifier_map
from wimpiggy.error import XError, trap

from wimpiggy.log import Logger
log = Logger()

import xpra
from xpra.protocol import Protocol, SocketConnection, dump_packet
from xpra.keys import mask_to_names, get_gtk_keymap, \
    DEFAULT_KEYNAME_FOR_MOD, DEFAULT_MODIFIER_NUISANCE, ALL_X11_MODIFIERS
from xpra.xkbhelper import do_set_keymap, set_all_keycodes, set_xmodmap_from_text, set_modifiers_from_meanings, clear_modifiers, set_modifiers_from_keycodes, set_modifiers_from_text
from xpra.xposix.xclipboard import ClipboardProtocolHelper
from xpra.xposix.xsettings import XSettingsManager
from xpra.scripts.main import ENCODINGS
from xpra.version_util import is_compatible_with

class DesktopManager(gtk.Widget):
    def __init__(self):
        gtk.Widget.__init__(self)
        self.set_property("can-focus", True)
        self.set_flags(gtk.NO_WINDOW)
        self._models = {}

    ## For communicating with the main WM:

    def add_window(self, model, x, y, w, h):
        assert self.flags() & gtk.REALIZED
        s = AdHocStruct()
        s.shown = False
        s.geom = (x, y, w, h)
        s.window = None
        self._models[model] = s
        model.connect("unmanaged", self._unmanaged)
        model.connect("ownership-election", self._elect_me)
        model.ownership_election()

    def window_geometry(self, model):
        return self._models[model].geom

    def show_window(self, model):
        self._models[model].shown = True
        model.ownership_election()
        if model.get_property("iconic"):
            model.set_property("iconic", False)

    def configure_window(self, model, x, y, w, h):
        if not self.visible(model):
            self._models[model].shown = True
            model.set_property("iconic", False)
            model.ownership_election()
        self._models[model].geom = (x, y, w, h)
        model.maybe_recalculate_geometry_for(self)

    def hide_window(self, model):
        if not model.get_property("iconic"):
            model.set_property("iconic", True)
        self._models[model].shown = False
        model.ownership_election()

    def visible(self, model):
        return self._models[model].shown

    def raise_window(self, model):
        if isinstance(model, OverrideRedirectWindowModel):
            model.get_property("client-window").raise_()
        else:
            window = self._models[model].window
            if window is not None:
                window.raise_()

    ## For communicating with WindowModels:

    def _unmanaged(self, model, wm_exiting):
        del self._models[model]

    def _elect_me(self, model):
        if self.visible(model):
            return (1, self)
        else:
            return (-1, self)

    def take_window(self, model, window):
        window.reparent(self.window, 0, 0)
        self._models[model].window = window

    def window_size(self, model):
        (_, _, w, h) = self._models[model].geom
        return (w, h)

    def window_position(self, model, w, h):
        (x, y, w0, h0) = self._models[model].geom
        if (w0, h0) != (w, h):
            log.warn("Uh-oh, our size doesn't fit window sizing constraints: "
                     "%sx%s vs %sx%s", w0, h0, w, h)
        return (x, y)

gobject.type_register(DesktopManager)

class ServerSource(object):
    """
    Strategy: if we have ordinary packets to send, send those.
    When we don't, then send window updates (expired ones first).
    The UI thread adds damage requests to a queue - see damage()
    """
    BATCH_EVENTS = True
    MAX_EVENTS = 80                     #maximum number of damage events
    MAX_PIXELS = 1024*1024*MAX_EVENTS   #small screen at MAX_EVENTS frames
    TIME_UNIT = 1                       #per second
    MIN_BATCH_DELAY = 5
    AVG_BATCH_DELAY = 100           #how long to batch updates for (in millis)
    MAX_BATCH_DELAY = 1000

    def __init__(self, protocol, encoding, send_damage_sequence, send_rowstride, mmap, mmap_size):
        self._ordinary_packets = []
        self._protocol = protocol
        self._encoding = encoding
        self._damage_cancelled = {}
        self._damage_last_events = {}
        self._damage_delayed = {}
        # for managing sequence numbers:
        self._send_damage_sequence = send_damage_sequence
        self._send_rowstride = send_rowstride
        self._sequence = 0                      #increase with every Region
        self._damage_packet_sequence = 0        #increase with every packet send
        self.last_client_packet_sequence = -1   #the last damage_packet_sequence the client echoed back to us
        self.last_client_delta = None           #last delta between our damage_packet_sequence and last_client_packet_sequence
        self.batch_delay = ServerSource.MIN_BATCH_DELAY
        # mmap:
        self._mmap = mmap
        self._mmap_size = mmap_size
        protocol.source = self
        self._damage_request_queue = Queue.Queue()
        self._damage_data_queue = Queue.Queue()
        self._damage_packet_queue = Queue.Queue(2)

        self._closed = False

        self._damagedata_thread = Thread(target=self.damage_to_data)
        self._damagedata_thread.name = "damage_to_data"
        self._damagedata_thread.daemon = True
        self._damagedata_thread.start()
        self._datapacket_thread = Thread(target=self.data_to_packet)
        self._datapacket_thread.name = "data_to_packet"
        self._datapacket_thread.daemon = True
        self._datapacket_thread.start()

    def close(self):
        self._closed = True

    def _have_more(self):
        return not self._closed and bool(self._ordinary_packets) or not self._damage_packet_queue.empty()

    def next_packet(self):
        if self._closed:
            return  None, False
        if self._ordinary_packets:
            packet = self._ordinary_packets.pop(0)
        else:
            try:
                packet = self._damage_packet_queue.get(False)
            except Queue.Empty:
                packet = None
        return packet, packet is not None and self._have_more()

    def send_packet_now(self, packet):
        assert self._protocol
        self._ordinary_packets.insert(0, packet)
        self._protocol.source_has_more()

    def queue_ordinary_packet(self, packet):
        assert self._protocol
        self._ordinary_packets.append(packet)
        self._protocol.source_has_more()

    def cancel_damage(self, id):
        #if delayed, we can just drop it now
        if id in self._damage_delayed:
            log("cancel_damage: %s, removed batched region", id)
            del self._damage_delayed[id]
        #for those being processed in separate threads, drop by sequence:
        log("cancel_damage: %s, dropping all damage up to sequence=%s", id, self._sequence)
        self._damage_cancelled[id] = self._sequence

    def damage(self, id, window, x, y, w, h, options=None):
        """ decide what to do with the damage area:
            * send it now (if not congested or BATCH_EVENTS is off)
            * add it to an existing delayed region
            * create a new delayed region if we find the client needs it
            Also takes care of adjusting the batch-delay in case
            of congestion.
            The options dict is currently used for carrying a different
            "jpegquality" from the default global one, it could also
            be used for other purposes. Be aware though that when multiple
            damage requests are delayed and bundled together,
            the options may get quashed! So, specify a "batching"=False
            option to ensure no batching will occur for this request.
        """
        def damage_now(reason):
            log("damage(%s, %s, %s, %s, %s) %s, sending now with sequence %s", id, x, y, w, h, reason, self._sequence)
            region = gtk.gdk.Region()
            region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
            item = id, window, region, self._sequence, options
            self._damage_request_queue.put(item)
            self._sequence += 1
        if not ServerSource.BATCH_EVENTS:
            return damage_now("batching disabled")

        #record this damage event in the damage_last_events queue:
        now = time.time()
        last_events = self._damage_last_events.setdefault(id, deque(maxlen=ServerSource.MAX_EVENTS))
        last_events.append((now, w*h))

        if options and options.get("batching", True) is False:
            damage_now("batching option is off")
            return

        delayed = self._damage_delayed.get(id)
        if delayed:
            (_, _, region, _, _) = delayed
            region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
            log("damage(%s, %s, %s, %s, %s) using existing delayed region: %s", id, x, y, w, h, delayed)
            return

        def update_batch_delay(reason, factor=1, delta=0):
            self.batch_delay = max(ServerSource.MIN_BATCH_DELAY, min(ServerSource.MAX_BATCH_DELAY, int(self.batch_delay*factor-delta)))
            log("update_batch_delay: %s, factor=%s, delta=%s, new batch delay=%s", reason, factor, delta, self.batch_delay)

        last_delta = self.last_client_delta
        delta = self._damage_packet_sequence-self.last_client_packet_sequence
        self.last_client_delta = delta
        if self._damage_packet_queue.full():
            update_batch_delay("damage packet queue is full", 1+sqrt(self.batch_delay)/10)
        elif self.last_client_packet_sequence>=0 and delta>5:
            if delta>10 or last_delta<delta:
                update_batch_delay("client %s damage packets behind" % delta, logp2(self._damage_packet_sequence-self.last_client_packet_sequence))
            else:
                update_batch_delay("client %s damage packets behind" % delta, 1.2)
        elif self._damage_request_queue.qsize()>3:
            update_batch_delay("damage request queue overflow: %s" % self._damage_request_queue.qsize(), 0.8+logp2(self._damage_request_queue.qsize()))
        elif self._damage_data_queue.qsize()>3:
            update_batch_delay("damage data queue overflow: %s" % self._damage_data_queue.qsize(), 0.8+logp2(self._damage_data_queue.qsize()))
        else:
            #if batch delay had been increased, reduce it:
            if self.batch_delay>ServerSource.MIN_BATCH_DELAY and (self.last_client_packet_sequence<0 or delta<=2):
                if self.last_client_packet_sequence<0:
                    update_batch_delay("no feedback... guessing", 0.8)
                elif self.batch_delay>ServerSource.AVG_BATCH_DELAY:
                    update_batch_delay("client up to date", 0.7+(delta*0.1))
                else:
                    update_batch_delay("client up to date", 1.0, 3-delta)
            else:
                pixel_count = 0
                for last_time,pixels in last_events:
                    pixel_count += pixels
                    if pixel_count>=ServerSource.MAX_PIXELS:
                        break
                if pixel_count>=ServerSource.MAX_PIXELS:
                    log("damage(%s, %s, %s, %s, %s) pixel storm: %s pixels in %s, batching", id, x, y, w, h, pixel_count, (now-last_time))
                else:
                    if len(last_events)<ServerSource.MAX_EVENTS:
                        return damage_now("recent event list is too small, not batching")
                    when,_ = last_events[0]
                    if now-when>ServerSource.TIME_UNIT:
                        return damage_now("%s damage events took %s seconds, not batching" % (ServerSource.MAX_EVENTS, (now-when)))
                    log("damage(%s, %s, %s, %s, %s) fast damage events: %s events in %s seconds, batching", id, x, y, w, h, ServerSource.MAX_EVENTS, (now-when))

        #create a new delayed region:
        region = gtk.gdk.Region()
        region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
        self._damage_delayed[id] = (id, window, region, self._sequence, options)
        self._sequence += 1
        def send_delayed():
            """ move the delayed rectangles to the expired list """
            log("send_delayed for %s", id)
            delayed = self._damage_delayed.get(id)
            if delayed:
                del self._damage_delayed[id]
                self._damage_request_queue.put(delayed)
                log("moving region %s to expired list", delayed)
            else:
                log("window %s already removed from delayed list?", id)
            return False
        log("damage(%s, %s, %s, %s, %s) scheduling batching expiry for sequence %s in %sms", id, x, y, w, h, self._sequence, self.batch_delay)
        gobject.timeout_add(self.batch_delay, send_delayed)

    def damage_to_data(self):
        """ pick items off the damage_request_queue
            and places the damage pixel data in the _damage_data_queue.
            this method runs in a thread but most of the actual processing
            is done in process_regions() which runs in the gtk main thread
            via idle_add.
        """
        while not self._closed:
            id, window, damage, sequence, options = self._damage_request_queue.get(True)
            log("damage_to_data: processing sequence=%s", sequence)
            if self._damage_cancelled.get(id, 0)>sequence:
                log("damage_to_data: dropping request with sequence=%s", sequence)
                continue
            regions = []
            try:
                if (isinstance(window, OverrideRedirectWindowModel)):
                    (_, _, ww, wh) = window.get_property("geometry")
                else:
                    ww, wh = window.get_property("actual-size")
            except KeyError, e:
                ww, wh = 512, 512
            try:
                full_pixels = ww*wh
                pixel_count = 0
                while not damage.empty():
                    try:
                        (x, y, w, h) = get_rectangle_from_region(damage)
                        pixel_count += w*h
                        #favor full screen updates over many regions:
                        if pixel_count+4096*len(regions)>=full_pixels*9/10:
                            regions = [(0, 0, ww, wh, True)]
                            break
                        regions.append((x, y, w, h, False))
                        rect = gtk.gdk.Rectangle(x, y, w, h)
                        damage.subtract(gtk.gdk.region_rectangle(rect))
                    except ValueError:
                        log.error("damage_to_data: damage is empty: %s", damage)
                        break
            except Exception, e:
                log.error("damage_to_data: error processing region %s: %s", damage, e)
                continue
            gobject.idle_add(self._process_damage_regions, id, window, ww, wh, regions, sequence, options)

    def _process_damage_regions(self, id, window, ww, wh, regions, sequence, options):
        if self._damage_cancelled.get(id, 0)>sequence:
            log("process_damage_regions: dropping damage request with sequence=%s", sequence)
            return
        # It's important to acknowledge changes *before* we extract them,
        # to avoid a race condition.
        log("process_damage_regions: regions=%s, sending damage ack", regions)
        window.acknowledge_changes()
        pixmap = window.get_property("client-contents")
        if pixmap is None:
            log.error("wtf, pixmap is None for window %s, id=%s", window, id)
            return
        log("process_damage_regions: pixmap size=%s, window size=%s", pixmap.get_size(), (ww, wh))
        for region in regions:
            (x, y, w, h, full_window) = region
            if full_window:
                log("process_damage_regions: sending full window: %s", pixmap.get_size())
                w, h = pixmap.get_size()
            data = self._get_rgb_rawdata(id, pixmap, x, y, w, h, sequence, options)
            if data:
                log("process_damage_regions: adding pixel data %s to queue, queue size=%s", data[:6], self._damage_data_queue.qsize())
                self._damage_data_queue.put(data)

    def _get_rgb_rawdata(self, id, pixmap, x, y, width, height, sequence, options):
        pixmap_w, pixmap_h = pixmap.get_size()
        # Just in case we somehow end up with damage larger than the pixmap,
        # we don't want to start requesting random chunks of memory (this
        # could happen if a window is resized but we don't throw away our
        # existing damage map):
        assert x >= 0
        assert y >= 0
        if x + width > pixmap_w:
            width = pixmap_w - x
        if y + height > pixmap_h:
            height = pixmap_h - y
        if width <= 0 or height <= 0:
            return None
        pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, width, height)
        pixbuf.get_from_drawable(pixmap, pixmap.get_colormap(),
                                 x, y, 0, 0, width, height)
        raw_data = pixbuf.get_pixels()
        rowstride = pixbuf.get_rowstride()
        return (id, x, y, width, height, self._encoding, raw_data, rowstride, sequence, options)


    def data_to_packet(self):
        while not self._closed:
            item = self._damage_data_queue.get(True)
            try:
                packet = self.make_data_packet(item)
                if packet:
                    log("data_to_packet: adding to packet queue, size=%s, full=%s", self._damage_packet_queue.qsize(), self._damage_packet_queue.full())
                    if self._damage_packet_queue.full():
                        self._protocol.source_has_more()
                    self._damage_packet_queue.put(packet)
                    self._protocol.source_has_more()
            except Exception, e:
                log.error("error processing damage data: %s", e)

    def make_data_packet(self, item):
        id, x, y, w, h, coding, data, rowstride, sequence, options = item
        if self._damage_cancelled.get(id, 0)>sequence:
            log("make_data_packet: dropping data packet with sequence=%s", sequence)
            return  None
        log("make_data_packet: damage data: %s", (id, x, y, w, h, coding))
        #remove rowstride padding but only if we can't send the rowstride value to client
        #removing the padding takes a lot of cpu/memory bandwidth for little benefit
        #not worth it, especially on large buffers
        rowwidth = w * 3
        if rowwidth!=rowstride and not (self._send_damage_sequence and self._send_rowstride):
            rows = []
            for i in xrange(h):
                rows.append(data[i*rowstride : i*rowstride+rowwidth])
            data = "".join(rows)
            rowstride = rowwidth
        #send via mmap?
        if self._mmap and self._mmap_size>0:
            mmap_data = self._mmap_send(data)
            if mmap_data is not None:
                coding = "mmap"
                data = mmap_data
        #encode to jpeg/png:
        if coding in ["jpeg", "png"]:
            import Image
            im = Image.fromstring("RGB", (w, h), data, "raw", "RGB", rowstride)
            buf = StringIO.StringIO()
            if self._encoding=="jpeg":
                q = self._protocol.jpegquality
                if options and "jpegquality" in options:
                    q = options.get("jpegquality")
                q = min(99, max(1, q))
                log.debug("sending with jpeg quality %s", q)
                im.save(buf, "JPEG", quality=q)
            else:
                log.debug("sending as %s", self._encoding)
                im.save(buf, self._encoding.upper())
            data = buf.getvalue()
            buf.close()
        #check cancellation list again since the code above may take some time:
        #but always send mmap data so we can reclaim the space!
        if self._damage_cancelled.get(id, 0)>sequence and coding!="mmap":
            log("make_data_packet: dropping data packet with sequence=%s", sequence)
            return  None
        #actual network packet:
        packet = ["draw", id, x, y, w, h, coding, data]
        if self._send_damage_sequence:
            packet.append(self._damage_packet_sequence)
            self._damage_packet_sequence += 1
            if self._send_rowstride:
                packet.append(rowstride)
        return packet

    def _mmap_send(self, data):
        #mmap_area=[&S&E-------------data-------------]
        #The first pair of 4 bytes are occupied by:
        #S=data_start index is only updated by the client and tells us where it has read up to
        #E=data_end index is only updated here and marks where we have written up to (matches current seek)
        # '-' denotes unused space
        # '+' is for data we have written
        # '*' is for data we have just written in this call
        # E and S show the location pointed to by data_start/data_end
        data_start = ctypes.c_uint.from_buffer(self._mmap, 0)
        data_end = ctypes.c_uint.from_buffer(self._mmap, 4)
        start = max(8, data_start.value)
        end = max(8, data_end.value)
        if end<start:
            #we have wrapped around but the client hasn't yet:
            #[++++++++E--------------------S+++++]
            #so there is one chunk available:
            available = start-end
            chunk = available
        else:
            #we have not wrapped around yet, or the client has wrapper around too:
            #[------------S++++++++++++E---------]
            #so there are two chunks available:
            chunk = self._mmap_size-end
            available = chunk+(start-8)
        l = len(data)
        if l>=available:
            log("mmap area full: we need more than %s but only %s left! ouch!", l, available)
            return None
        if l<chunk:
            """ data fits in the first chunk """
            #ie: initially:
            #[----------------------------------]
            #[*********E------------------------]
            #or if data already existed:
            #[+++++++++E------------------------]
            #[+++++++++**********E--------------]
            self._mmap.seek(end)
            self._mmap.write(data)
            data = [(end, l)]
            data_end.value = end+l
        else:
            """ data does not fit in first chunk alone """
            if available>=(self._mmap_size/2) and available>=(l*3) and l<(start-8):
                """ still plenty of free space, don't wrap around: just start again """
                #[------------------S+++++++++E------]
                #[*******E----------S+++++++++-------]
                self._mmap.seek(8)
                self._mmap.write(data)
                data = [(8, l)]
                data_end.value = 8+l
            else:
                """ split in 2 chunks: wrap around the end of the mmap buffer """
                #[------------------S+++++++++E------]
                #[******E-----------S+++++++++*******]
                self._mmap.seek(end)
                self._mmap.write(data[:chunk])
                self._mmap.seek(8)
                self._mmap.write(data[chunk:])
                l2 = l-chunk
                data = [(end, chunk), (8, l2)]
                data_end.value = 8+l2
        log("sending damage with mmap: %s", data)
        return data


class XpraServer(gobject.GObject):
    __gsignals__ = {
        "wimpiggy-child-map-event": one_arg_signal,
        "wimpiggy-cursor-event": one_arg_signal,
        }

    def __init__(self, clobber, sockets, session_name, password_file, pulseaudio, clipboard, randr, encoding, mmap):
        gobject.GObject.__init__(self)

        self.start_time = time.time()

        # Do this before creating the Wm object, to avoid clobbering its
        # selecting SubstructureRedirect.
        root = gtk.gdk.get_default_root_window()
        root.set_events(root.get_events() | gtk.gdk.SUBSTRUCTURE_MASK)
        root.property_change(gtk.gdk.atom_intern("XPRA_SERVER", False),
                            gtk.gdk.atom_intern("STRING", False),
                            8,
                            gtk.gdk.PROP_MODE_REPLACE,
                            xpra.__version__)
        add_event_receiver(root, self)

        # This must happen early, before loading in windows at least:
        self._protocol = None
        self._potential_protocols = []
        self._server_source = None

        self.supports_mmap = mmap
        self.encoding = encoding or "rgb24"
        assert self.encoding in ENCODINGS
        self.png_window_icons = False
        self.session_name = session_name
        import glib
        glib.set_application_name(self.session_name or "Xpra")

        ### Create the WM object
        self._wm = Wm("Xpra", clobber)
        self._wm.connect("new-window", self._new_window_signaled)
        self._wm.connect("bell", self._bell_signaled)
        self._wm.connect("quit", lambda _: self.quit(True))

        ### Create our window managing data structures:
        self._desktop_manager = DesktopManager()
        self._wm.get_property("toplevel").add(self._desktop_manager)
        self._desktop_manager.show_all()

        self._window_to_id = {}
        self._id_to_window = {}
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1

        ### Load in existing windows:
        for window in self._wm.get_property("windows"):
            self._add_new_window(window)

        for window in get_children(root):
            if (is_override_redirect(window) and is_mapped(window)):
                self._add_new_or_window(window)

        ## These may get set by the client:
        self.xkbmap_layout = None
        self.xkbmap_variant = None
        self.xkbmap_print = None
        self.xkbmap_query = None
        self.xkbmap_mod_meanings = {}
        self.xkbmap_mod_managed = []
        self.xmodmap_data = None
        self.keycode_translation = {}
        self.keymap_changing = False
        self.keyboard_sync = True
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        self.encodings = ["rgb24"]
        self.mmap = None
        self.mmap_size = 0

        self.reset_statistics()

        self.send_damage_sequence = False
        self.send_notifications = False
        self.last_cursor_serial = None
        self.cursor_image = None
        #store list of currently pressed keys
        #(using a dict only so we can display their names in debug messages)
        self.keys_pressed = {}
        self.keys_timedout = {}
        #timers for cancelling key repeat when we get jitter
        self.keys_repeat_timers = {}
        ### Set up keymap:
        self.xkbmap_initial = get_gtk_keymap()
        self._keymap = gtk.gdk.keymap_get_default()
        self._keymap.connect("keys-changed", self._keys_changed)
        self._keys_changed()

        self._keynames_for_mod = DEFAULT_KEYNAME_FOR_MOD.copy()
        #clear all modifiers
        self._make_keymask_match([])

        ### Clipboard handling:
        self.clipboard_enabled = clipboard
        if clipboard:
            def send_clipboard(packet):
                if self.clipboard_enabled:
                    self._send(packet)
                else:
                    log.debug("clipboard is disabled, dropping packet")
            self._clipboard_helper = ClipboardProtocolHelper(send_clipboard)
        else:
            self._clipboard_helper = None

        ### Misc. state:
        self._settings = {}
        self._xsettings_manager = None
        self._has_focus = 0
        self._upgrading = False

        self.password_file = password_file
        self.salt = None

        self.randr = randr and has_randr()
        if self.randr and len(get_screen_sizes())<=1:
            #disable randr when we are dealing with a Xvfb
            #with only one resolution available
            #since we don't support adding them on the fly yet
            self.randr = False
        log.info("randr enabled: %s", self.randr)

        self.pulseaudio = pulseaudio

        try:
            from xpra.dbus_notifications_forwarder import register
            self.notifications_forwarder = register(self.notify_callback, self.notify_close_callback, replace=True)
            log.info("using notification forwarder")
        except Exception, e:
            log.error("failed to load dbus notifications forwarder: %s", e)
            self.notifications_forwarder = None

        ### All right, we're ready to accept customers:
        for sock in sockets:
            self.add_listen_socket(sock)

    def reset_statistics(self):
        self.client_latency = deque(maxlen=100)
        self.client_load = None
        self.server_latency = -1

    def set_keymap(self):
        def clean_state():
            try:
                ungrab_all_keys(gtk.gdk.get_default_root_window())
            except:
                log.error("error ungrabbing keys", exc_info=True)
            try:
                unpress_all_keys(gtk.gdk.get_default_root_window())
            except:
                log.error("error unpressing keys", exc_info=True)
        try:
            #prevent _keys_changed() from firing:
            #(using a flag instead of keymap.disconnect(handler) as this did not seem to work!)
            self.keymap_changing = True
            clean_state()
            try:
                do_set_keymap(self.xkbmap_layout, self.xkbmap_variant,
                              self.xkbmap_print, self.xkbmap_query)
            except:
                log.error("error setting new keymap", exc_info=True)
            try:
                #first clear all existing modifiers:
                clean_state()
                modifiers = ALL_X11_MODIFIERS.keys()  #just clear all of them (set or not)
                clear_modifiers(modifiers)

                #now set all the keycodes:
                clean_state()
                if len(self.xkbmap_keycodes)>0:
                    #version 0.0.7.33 and above:
                    self.keycode_translation = set_all_keycodes(self.xkbmap_keycodes, self.xkbmap_initial)
                else:
                    self.keycode_translation = {}
                    set_xmodmap_from_text(self.xmodmap_data)

                #now set the new modifier mappings:
                clean_state()
                log.debug("going to set modifiers, xkbmap_mod_meanings=%s, len(xkbmap_keycodes)=%s", self.xkbmap_mod_meanings, len(self.xkbmap_keycodes))
                if self.xkbmap_mod_meanings:
                    #version 0.0.7.33 and above with Unix-like OS:
                    self._keynames_for_mod = set_modifiers_from_meanings(self.xkbmap_mod_meanings)
                elif self.xkbmap_keycodes:
                    #version 0.0.7.33 and above with non-Unix-like OS:
                    self._keynames_for_mod = set_modifiers_from_keycodes(self.xkbmap_keycodes)
                else:
                    #older versions: try our best...
                    self._keynames_for_mod = set_modifiers_from_text(self.xkbmap_mod_add)

                clean_state()
                #build keynames_for_mod
                log.debug("keyname_for_mod=%s", self._keynames_for_mod)
            except:
                log.error("error setting xmodmap", exc_info=True)
        finally:
            # re-enable via idle_add to give all the pending
            # events a chance to run first (and get ignored)
            def reenable_keymap_changes(*args):
                self.keymap_changing = False
                self._keys_changed()
            gobject.idle_add(reenable_keymap_changes)


    def add_listen_socket(self, sock):
        sock.listen(5)
        gobject.io_add_watch(sock, gobject.IO_IN, self._new_connection, sock)

    def quit(self, upgrading):
        self._upgrading = upgrading
        log.info("\nxpra is terminating.")
        sys.stdout.flush()
        gtk_main_quit_really()

    def run(self):
        gtk_main_quit_on_fatal_exceptions_enable()
        def print_ready():
            log.info("\nxpra is ready.")
            sys.stdout.flush()
        gobject.idle_add(print_ready)
        gtk.main()
        log.info("\nxpra end of gtk.main().")
        return self._upgrading

    def cleanup(self, *args):
        self.disconnect("shutting down")

    def _new_connection(self, listener, *args):
        log.info("New connection received")
        sock, _ = listener.accept()
        self._potential_protocols.append(Protocol(SocketConnection(sock),
                                                  self.process_packet))
        return True

    def _keys_changed(self, *args):
        if not self.keymap_changing:
            self._modifier_map = grok_modifier_map(gtk.gdk.display_get_default(), self.xkbmap_mod_meanings)

    def _new_window_signaled(self, wm, window):
        self._add_new_window(window)

    def do_wimpiggy_cursor_event(self, event):
        if self.last_cursor_serial==event.cursor_serial:
            log("ignoring cursor event with the same serial number")
            return
        self.last_cursor_serial = event.cursor_serial
        self.cursor_image = get_cursor_image()
        log("do_wimpiggy_cursor_event(%s) new_cursor=%s", event, self.cursor_image[:7])
        self.send_cursor()

    def send_cursor(self):
        self._send(["cursor", self.cursor_image or ""])

    def _bell_signaled(self, wm, event):
        log("_bell_signaled(%s,%r)", wm, event)
        if not self.send_bell:
            return
        id = 0
        if event.window!=gtk.gdk.get_default_root_window() and event.window_model is not None:
            try:
                id = self._window_to_id[event.window_model]
            except:
                pass
        log("_bell_signaled(%s,%r) id=%s", wm, event, id)
        self._send(["bell", id, event.device, event.percent, event.pitch, event.duration, event.bell_class, event.bell_id, event.bell_name])

    def notify_callback(self, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        log("notify_callback(%s,%s,%s,%s,%s,%s,%s,%s) send_notifications=%s", dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout, self.send_notifications)
        if self.send_notifications:
            self._send(["notify_show", dbus_id, int(id), str(app_name), int(replaces_id), str(app_icon), str(summary), str(body), long(expire_timeout)])

    def notify_close_callback(self, id):
        log("notify_close_callback(%s)", id)
        if self.send_notifications:
            self._send(["notify_close", int(id)])

    def do_wimpiggy_child_map_event(self, event):
        raw_window = event.window
        if event.override_redirect:
            self._add_new_or_window(raw_window)

    def _add_new_window_common(self, window):
        id = self._max_window_id
        self._max_window_id += 1
        self._window_to_id[window] = id
        self._id_to_window[id] = window
        window.connect("client-contents-changed", self._contents_changed)
        window.connect("unmanaged", self._lost_window)

    _window_export_properties = ("title", "size-hints")
    def _add_new_window(self, window):
        log("Discovered new ordinary window")
        self._add_new_window_common(window)
        for prop in self._window_export_properties:
            window.connect("notify::%s" % prop, self._update_metadata)
        (x, y, w, h, _) = window.get_property("client-window").get_geometry()
        self._desktop_manager.add_window(window, x, y, w, h)
        self._send_new_window_packet(window)

    def _add_new_or_window(self, raw_window):
        log("Discovered new override-redirect window")
        try:
            window = OverrideRedirectWindowModel(raw_window)
        except Unmanageable:
            return
        self._add_new_window_common(window)
        window.connect("notify::geometry", self._or_window_geometry_changed)
        self._send_new_or_window_packet(window)

    def _or_window_geometry_changed(self, window, pspec):
        (x, y, w, h) = window.get_property("geometry")
        id = self._window_to_id[window]
        self._send(["configure-override-redirect", id, x, y, w, h])

    # These are the names of WindowModel properties that, when they change,
    # trigger updates in the xpra window metadata:
    _all_metadata = ("title", "size-hints", "class-instance", "icon", "client-machine")

    # Takes the name of a WindowModel property, and returns a dictionary of
    # xpra window metadata values that depend on that property:
    def _make_metadata(self, window, propname):
        assert propname in self._all_metadata
        if propname == "title":
            if window.get_property("title") is not None:
                return {"title": window.get_property("title").encode("utf-8")}
            else:
                return {}
        elif propname == "size-hints":
            hints_metadata = {}
            hints = window.get_property("size-hints")
            if hints is not None:
                for attr, metakey in [
                    ("max_size", "maximum-size"),
                    ("min_size", "minimum-size"),
                    ("base_size", "base-size"),
                    ("resize_inc", "increment"),
                    ("min_aspect_ratio", "minimum-aspect"),
                    ("max_aspect_ratio", "maximum-aspect"),
                    ]:
                    v = getattr(hints, attr)
                    if v is not None and v>=0 and v<(2**32-1):
                        hints_metadata[metakey] = getattr(hints, attr)
            return {"size-constraints": hints_metadata}
        elif propname == "class-instance":
            c_i = window.get_property("class-instance")
            if c_i is not None:
                return {"class-instance": [x.encode("utf-8") for x in c_i]}
            else:
                return {}
        elif propname == "icon":
            surf = window.get_property("icon")
            if surf is not None:
                w = surf.get_width()
                h = surf.get_height()
                log("found new window icon: %sx%s, sending as png=%s", w,h,self.png_window_icons)
                if self.png_window_icons:
                    import Image
                    img = Image.frombuffer("RGBA", (w,h), surf.get_data(), "raw", "BGRA", 0, 1)
                    MAX_SIZE = 64
                    if w>MAX_SIZE or h>MAX_SIZE:
                        #scale icon down
                        if w>=h:
                            h = int(h*MAX_SIZE/w)
                            w = MAX_SIZE
                        else:
                            w = int(w*MAX_SIZE/h)
                            h = MAX_SIZE
                        log("scaling window icon down to %sx%s", w, h)
                        img = img.resize((w,h), Image.ANTIALIAS)
                    output = StringIO.StringIO()
                    img.save(output, 'PNG')
                    raw_data = output.getvalue()
                    return {"icon": (w, h, "png", str(raw_data)) }
                else:

                    assert surf.get_format() == cairo.FORMAT_ARGB32
                    assert surf.get_stride() == 4 * surf.get_width()
                    return {"icon": (w, h, "premult_argb32", str(surf.get_data())) }
            else:
                return {}
        elif propname == "client-machine":
            client_machine = window.get_property("client-machine")
            if client_machine is not None:
                return {"client-machine": client_machine.encode("utf-8")}
            else:
                return {}

        else:
            assert False

    def _keycodes(self, keyname):
        keyval = gtk.gdk.keyval_from_name(keyname)
        if keyval==0:
            log.error("no keyval found for %s", keyname)
            return  []
        entries = self._keymap.get_entries_for_keyval(keyval)
        keycodes = []
        if entries:
            for _keycode,_group,_level in entries:
                keycodes.append(_keycode)
        return  keycodes

    def _keycode(self, keycode, keyval, keyname, group=0, level=0):
        log.debug("keycode(%s,%s,%s,%s,%s)", keycode, keyval, keyname, group, level)
        if keycode and self.xkbmap_print is not None:
            """ versions 0.0.7.24 and above give us the raw keycode,
                we can only use this if we have applied the same keymap - if the client sent one
            """
            return  keycode
        # fallback code for older versions:
        kv = keyval
        if not keyval:
            kn = keyname
            if len(kn)>0 and kn[-1]=="\0":
                kn = kn[:-1]
            kv = gtk.gdk.keyval_from_name(kn)
        entries = self._keymap.get_entries_for_keyval(kv)
        if not entries:
            log.error("no keycode found for keyname=%s, keyval=%s", keyname, kv)
            return None
        kc = -1
        if group>=0:
            for _keycode,_group,_level in entries:
                if _group!=group:
                    continue
                if kc==-1 or _level==level:
                    kc = _keycode
        log.debug("keycode(%s,%s,%s,%s,%s) keyval=%s, kc=%s, entries=%s", keycode, keyval, keyname, group, level, kv, kc, entries)
        if kc>0:
            return  kc
        return entries[0][0]    #nasty fallback!

    def _make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        """
            Given a list of modifiers that should be set, try to press the right keys
            to make the server's modifier list match it.
            Things to take into consideration:
            * xkbmap_mod_managed is a list of modifiers which are "server-managed":
                these never show up in the client's modifier list as it is not aware of them,
                so we just always leave them as they are and rely on some client key event to toggle them.
                ie: "num" on win32, which is toggled by the "Num_Lock" key presses.
            * when called from '_handle_key', we ignore the modifier key which may be pressed
                or released as it should be set by that key press event.
            * when called from mouse position/click events we ignore 'xkbmap_mod_pointermissing'
                which is set by the client to indicate modifiers which are missing from mouse events.
                ie: on win32, "lock" is missing.
            * if the modifier is a "nuisance" one ("lock", "num", "scroll") then we must
                simulate a full keypress (down then up).
            * some modifiers can be set by multiple keys ("shift" by both "Shift_L" and "Shift_R" for example)
                so we try to find the matching modifier in the currently pressed keys (keys_pressed)
                to make sure we unpress the right one.
        """
        #FIXME: we should probably cache the keycode
        # and clear the cache in _keys_changed
        def get_current_mask():
            (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
            modifiers = mask_to_names(current_mask, self._modifier_map)
            log.debug("get_modifier_mask()=%s", modifiers)
            return modifiers
        current = set(get_current_mask())
        wanted = set(modifier_list)
        log.debug("make_keymask_match(%s) current mask: %s, wanted: %s, ignoring=%s/%s, keys_pressed=%s", modifier_list, current, wanted, ignored_modifier_keycode, ignored_modifier_keynames, self.keys_pressed)
        display = gtk.gdk.display_get_default()

        def change_mask(modifiers, press, info):
            for modifier in modifiers:
                if self.xkbmap_mod_managed and modifier in self.xkbmap_mod_managed:
                    log.debug("modifier is server managed: %s", modifier)
                    continue
                keynames = self._keynames_for_mod.get(modifier)
                if not keynames:
                    log.error("unknown modifier: %s", modifier)
                    continue
                if ignored_modifier_keynames:
                    for imk in ignored_modifier_keynames:
                        if imk in keynames:
                            log.debug("modifier %s ignored (ignored keyname=%s)", modifier, imk)
                            continue
                keycodes = []
                #log.info("keynames(%s)=%s", modifier, keynames)
                for keyname in keynames:
                    if keyname in self.keys_pressed.values():
                        #found the key which was pressed to set this modifier
                        for keycode, name in self.keys_pressed.items():
                            if name==keyname:
                                log.debug("found the key pressed for %s: %s", modifier, name)
                                keycodes.insert(0, keycode)
                    kcs = self._keycodes(keyname)
                    for kc in kcs:
                        if kc not in keycodes:
                            keycodes.append(kc)
                if ignored_modifier_keycode is not None and ignored_modifier_keycode in keycodes:
                    log.debug("modifier %s ignored (ignored keycode=%s)", modifier, ignored_modifier_keycode)
                    continue
                #nuisance keys (lock, num, scroll) are toggled by a
                #full key press + key release (so act accordingly in the loop below)
                nuisance = modifier in DEFAULT_MODIFIER_NUISANCE
                log.debug("keynames(%s)=%s, keycodes=%s, nuisance=%s", modifier, keynames, keycodes, nuisance)
                for keycode in keycodes:
                    if nuisance:
                        xtest_fake_key(display, keycode, True)
                        xtest_fake_key(display, keycode, False)
                    else:
                        xtest_fake_key(display, keycode, press)
                    new_mask = get_current_mask()
                    #log.debug("make_keymask_match(%s) %s modifier %s using %s: %s", info, modifier_list, modifier, keycode, (modifier not in new_mask))
                    if (modifier in new_mask)==press:
                        break
                    elif not nuisance:
                        log.debug("%s %s with keycode %s did not work - trying to undo it!", info, modifier, keycode)
                        xtest_fake_key(display, keycode, not press)
                        new_mask = get_current_mask()
                        #maybe doing the full keypress (down+up or u+down) worked:
                        if (modifier in new_mask)==press:
                            break

        change_mask(current.difference(wanted), False, "remove")
        change_mask(wanted.difference(current), True, "add")

    def _clear_keys_pressed(self):
        #make sure the timers don't fire and interfere:
        if len(self.keys_repeat_timers)>0:
            for timer in self.keys_repeat_timers.values():
                gobject.source_remove(timer)
            self.keys_repeat_timers = {}
        #clear all the keys we know about:
        if len(self.keys_pressed)>0:
            log.debug("clearing keys pressed: %s", self.keys_pressed)
            for keycode in self.keys_pressed.keys():
                xtest_fake_key(gtk.gdk.display_get_default(), keycode, False)
            self.keys_pressed = {}
        #this will take care of any remaining ones we are not aware of:
        #(there should not be any - but we want to be certain)
        unpress_all_keys(gtk.gdk.display_get_default())

    def _focus(self, id, modifiers):
        log.debug("_focus(%s,%s) has_focus=%s", id, modifiers, self._has_focus)
        if self._has_focus != id:
            if id == 0:
                self._clear_keys_pressed()
                # FIXME: kind of a hack:
                self._wm.get_property("toplevel").reset_x_focus()
            else:
                window = self._id_to_window[id]
                #no idea why we can't call this straight away!
                #but with win32 clients, it would often fail!???
                def give_focus():
                    window.give_client_focus()
                    return False
                gobject.idle_add(give_focus)
                if modifiers is not None:
                    self._make_keymask_match(modifiers, self.xkbmap_mod_pointermissing)
            self._has_focus = id

    def _move_pointer(self, pos):
        (x, y) = pos
        display = gtk.gdk.display_get_default()
        display.warp_pointer(display.get_default_screen(), x, y)

    def _send(self, packet):
        if self._protocol is not None:
            log("Queuing packet: %s", dump_packet(packet))
            self._protocol.source.queue_ordinary_packet(packet)

    def _raw_send(self, proto, packet):
        #this method is only used before we create the server source
        socket = proto._conn._s
        log.debug("proto=%s, conn=%s, socket=%s", repr(proto), repr(proto._conn), socket)
        from xpra.bencode import bencode
        import select
        data = bencode(packet)
        written = 0
        while written < len(data):
            select.select([], [socket], [])
            written += socket.send(data[written:])

    def _damage(self, window, x, y, width, height, options=None):
        if self._protocol is not None and self._protocol.source is not None:
            id = self._window_to_id[window]
            self._protocol.source.damage(id, window, x, y, width, height, options)

    def _cancel_damage(self, window):
        if self._protocol is not None and self._protocol.source is not None:
            id = self._window_to_id[window]
            self._protocol.source.cancel_damage(id)

    def _send_new_window_packet(self, window):
        id = self._window_to_id[window]
        (x, y, w, h) = self._desktop_manager.window_geometry(window)
        metadata = {}
        for propname in self._all_metadata:
            metadata.update(self._make_metadata(window, propname))
        self._send(["new-window", id, x, y, w, h, metadata])

    def _send_new_or_window_packet(self, window):
        id = self._window_to_id[window]
        (x, y, w, h) = window.get_property("geometry")
        self._send(["new-override-redirect", id, x, y, w, h, {}])
        self._damage(window, 0, 0, w, h)

    def _update_metadata(self, window, pspec):
        id = self._window_to_id[window]
        metadata = self._make_metadata(window, pspec.name)
        self._send(["window-metadata", id, metadata])

    def _lost_window(self, window, wm_exiting):
        id = self._window_to_id[window]
        self._send(["lost-window", id])
        self._cancel_damage(window)
        del self._window_to_id[window]
        del self._id_to_window[id]
        if self._server_source and id in self._server_source._damage_last_events:
            del self._server_source._damage_last_events[id]

    def _contents_changed(self, window, event):
        if (isinstance(window, OverrideRedirectWindowModel)
            or self._desktop_manager.visible(window)):
            self._damage(window, event.x, event.y, event.width, event.height)

    def _get_desktop_size_capability(self, client_capabilities):
        (root_w, root_h) = gtk.gdk.get_default_root_window().get_size()
        client_size = client_capabilities.get("desktop_size")
        log.info("client resolution is %s, current server resolution is %sx%s", client_size, root_w, root_h)
        if not client_size:
            """ client did not specify size, just return what we have """
            return    root_w, root_h
        client_w, client_h = client_size
        if not self.randr:
            """ server does not support randr - return minimum of the client/server dimensions """
            w = min(client_w, root_w)
            h = min(client_h, root_h)
            return    w,h
        log.debug("client resolution is %sx%s, current server resolution is %sx%s", client_w, client_h, root_w, root_h)
        return self.set_screen_size(client_w, client_h)

    def set_screen_size(self, client_w, client_h):
        (root_w, root_h) = gtk.gdk.get_default_root_window().get_size()
        if client_w==root_w and client_h==root_h:
            return    root_w,root_h    #unlikely: perfect match already!
        #try to find the best screen size to resize to:
        new_size = None
        for w,h in get_screen_sizes():
            if w<client_w or h<client_h:
                continue            #size is too small for client
            if new_size:
                ew,eh = new_size
                if ew*eh<w*h:
                    continue        #we found a better (smaller) candidate already
            new_size = w,h
        log.debug("best resolution for client(%sx%s) is: %s", client_w, client_h, new_size)
        if new_size:
            w, h = new_size
            if w==root_w and h==root_h:
                log.info("best resolution for client %sx%s is unchanged: %sx%s", client_w, client_h, w, h)
            else:
                try:
                    set_screen_size(w, h)
                    (root_w, root_h) = get_screen_size()
                    if root_w!=w or root_h!=h:
                        log.error("odd, failed to set the new resolution, "
                                  "tried to set it to %sx%s and ended up with %sx%s", w, h, root_w, root_h)
                    else:
                        log.info("new resolution set for client %sx%s : screen now set to %sx%s", client_w, client_h, root_w, root_h)
                except Exception, e:
                    log.error("ouch, failed to set new resolution: %s", e, exc_info=True)
        w = min(client_w, root_w)
        h = min(client_h, root_h)
        return w,h

    def _process_desktop_size(self, proto, packet):
        (_, width, height) = packet
        log.debug("client requesting new size: %sx%s", width, height)
        self.set_screen_size(width, height)

    def _set_encoding(self, encoding):
        if encoding:
            assert encoding in self.encodings
            if encoding not in ENCODINGS:
                log.error("encoding %s is not supported by this server! " \
                         "Will use the first commonly supported encoding instead", encoding)
                encoding = None
        else:
            log.debug("encoding not specified, will use the first match")
        if not encoding:
            #not specified or not supported, find intersection of supported encodings:
            common = [e for e in self.encodings if e in ENCODINGS]
            log.debug("encodings supported by both ends: %s", common)
            if not common:
                raise Exception("cannot find compatible encoding between "
                                "client (%s) and server (%s)" % (self.encodings, ENCODINGS))
            encoding = common[0]
        self.encoding = encoding
        if self._server_source is not None:
            self._server_source._encoding = encoding
        log.info("encoding set to %s, client supports %s, server supports %s", encoding, self.encodings, ENCODINGS)

    def _process_encoding(self, proto, packet):
        (_, encoding) = packet
        self._set_encoding(encoding)

    def _send_password_challenge(self, proto):
        self.salt = "%s" % uuid.uuid4()
        log.info("Password required, sending challenge")
        packet = ("challenge", self.salt)
        self._raw_send(proto, packet)

    def _verify_password(self, proto, client_hash):
        passwordFile = open(self.password_file, "rU")
        password  = passwordFile.read()
        hash = hmac.HMAC(password, self.salt)
        if client_hash != hash.hexdigest():
            def login_failed(*args):
                log.error("Password supplied does not match! dropping the connection.")
                try:
                    self._raw_send(proto, ["disconnect", "invalid password"])
                    proto.close()
                except Exception, e:
                    log.error("password does not match and failed to close connection %s: %s", proto, e)
            gobject.timeout_add(1000, login_failed)
            return False
        self.salt = None            #prevent replay attacks
        log.info("Password matches!")
        sys.stdout.flush()
        return True

    def _process_hello(self, proto, packet):
        (_, capabilities) = packet
        log.info("Handshake complete; enabling connection")
        remote_version = capabilities.get("__prerelease_version")
        if not is_compatible_with(remote_version):
            proto.close()
            return
        if self.password_file:
            log.debug("password auth required")
            client_hash = capabilities.get("challenge_response")
            if not client_hash or not self.salt:
                self._send_password_challenge(proto)
                return
            del capabilities["challenge_response"]
            if not self._verify_password(proto, client_hash):
                return

        # Okay, things are okay, so let's boot out any existing connection and
        # set this as our new one:
        if self._protocol is not None:
            self.disconnect("new valid connection received")
        self.reset_statistics()
        self.send_damage_sequence = capabilities.get("damage_sequence", False)
        self.send_rowstride = self.send_damage_sequence and capabilities.get("rowstride", False)
        #if "encodings" not specified, use pre v0.0.7.26 default: rgb24
        self.encodings = capabilities.get("encodings", ["rgb24"])
        self._set_encoding(capabilities.get("encoding", None))
        #mmap:
        self.close_mmap()
        mmap_file = capabilities.get("mmap_file")
        log("client supplied mmap_file=%s, mmap supported=%s", mmap_file, self.supports_mmap)
        if self.supports_mmap and mmap_file and os.path.exists(mmap_file):
            import mmap
            f = open(mmap_file, "r+b")
            self.mmap_size = os.path.getsize(mmap_file)
            self.mmap = mmap.mmap(f.fileno(), self.mmap_size)
            mmap_token = capabilities.get("mmap_token")
            if mmap_token:
                #verify the token:
                v = 0
                for i in range(0,16):
                    v = v<<8
                    peek = ctypes.c_ubyte.from_buffer(self.mmap, 512+15-i)
                    v += peek.value
                log.debug("mmap_token=%s, verification=%s", mmap_token, v)
                if v!=mmap_token:
                    log.error("WARNING: mmap token verification failed, not using mmap area!")
                    self.close_mmap()
            if self.mmap:
                log.info("using client supplied mmap file=%s, size=%s", mmap_file, self.mmap_size)
        self._protocol = proto
        self._server_source = ServerSource(self._protocol, self.encoding, self.send_damage_sequence, self.send_rowstride, self.mmap, self.mmap_size)
        # do screen size calculations/modifications:
        self.send_hello(capabilities)
        if "deflate" in capabilities and not capabilities.get("dynamic_compression", False):
            #"deflate" is the old-style (pre 0.0.7.33): enable straight away:
            self._protocol.enable_deflate(capabilities["deflate"])
        self._protocol._send_size = capabilities.get("packet_size", False)
        if "jpeg" in capabilities:
            self._protocol.jpegquality = capabilities["jpeg"]
        self.keyboard_sync = capabilities.get("keyboard_sync", True)
        key_repeat = capabilities.get("key_repeat", None)
        if key_repeat:
            self.key_repeat_delay, self.key_repeat_interval = key_repeat
            if self.key_repeat_delay>0 and self.key_repeat_interval>0:
                set_key_repeat_rate(self.key_repeat_delay, self.key_repeat_interval)
                log.info("setting key repeat rate from client: %s / %s", self.key_repeat_delay, self.key_repeat_interval)
        else:
            #dont do any jitter compensation:
            self.key_repeat_delay = -1
            self.key_repeat_interval = -1
            #but do set a default repeat rate:
            set_key_repeat_rate(500, 30)
        self.xkbmap_layout = capabilities.get("xkbmap_layout")
        self.xkbmap_variant = capabilities.get("xkbmap_variant")
        self.xkbmap_print = capabilities.get("keymap")
        self.xkbmap_query = capabilities.get("xkbmap_query")
        self.xmodmap_data = capabilities.get("xmodmap_data")
        self.xkbmap_mod_clear = capabilities.get("xkbmap_mod_clear")
        self.xkbmap_mod_add = capabilities.get("xkbmap_mod_add")
        self.xkbmap_mod_meanings = capabilities.get("xkbmap_mod_meanings")
        self.xkbmap_mod_managed = capabilities.get("xkbmap_mod_managed", [])
        self.xkbmap_mod_pointermissing = capabilities.get("xkbmap_mod_pointermissing")
        self.xkbmap_keycodes = capabilities.get("xkbmap_keycodes", [])

        #always clear modifiers before setting a new keymap
        self._make_keymask_match([])
        self.set_keymap()
        self.send_cursors = capabilities.get("cursors", False)
        self.send_bell = capabilities.get("bell", False)
        self.send_notifications = capabilities.get("notifications", False)
        self.can_ping = capabilities.get("ping", False)
        self.clipboard_enabled = capabilities.get("clipboard", True) and self._clipboard_helper is not None
        log.debug("cursors=%s, bell=%s, notifications=%s, clipboard=%s", self.send_cursors, self.send_bell, self.send_notifications, self.clipboard_enabled)
        self._wm.enableCursors(self.send_cursors)
        self.png_window_icons = capabilities.get("png_window_icons", False) and "png" in ENCODINGS
        # now we can set the modifiers to match the client
        modifiers = capabilities.get("modifiers", [])
        log.debug("setting modifiers to %s", modifiers)
        self._make_keymask_match(modifiers)
        # We send the new-window packets sorted by id because this sorts them
        # from oldest to newest -- and preserving window creation order means
        # that the earliest override-redirect windows will be on the bottom,
        # which is usually how things work.  (I don't know that anyone cares
        # about this kind of correctness at all, but hey, doesn't hurt.)
        for id in sorted(self._id_to_window.iterkeys()):
            window = self._id_to_window[id]
            if isinstance(window, OverrideRedirectWindowModel):
                self._send_new_or_window_packet(window)
            else:
                self._desktop_manager.hide_window(window)
                self._send_new_window_packet(window)
        if self.send_cursors:
            self.send_cursor()

    def send_hello(self, client_capabilities):
        capabilities = {}
        capabilities["__prerelease_version"] = xpra.__version__
        if "deflate" in client_capabilities:
            capabilities["deflate"] = client_capabilities.get("deflate")
        capabilities["desktop_size"] = self._get_desktop_size_capability(client_capabilities)
        capabilities["actual_desktop_size"] = gtk.gdk.get_default_root_window().get_size()
        capabilities["platform"] = sys.platform
        capabilities["raw_keycodes_feature"] = True
        capabilities["raw_keycodes_full"] = True
        capabilities["focus_modifiers_feature"] = True
        capabilities["dynamic_compression"] = True
        capabilities["packet_size"] = True
        capabilities["cursors"] = True
        capabilities["bell"] = True
        capabilities["notifications"] = True
        capabilities["clipboard"] = self.clipboard_enabled
        capabilities["png_window_icons"] = "png" in ENCODINGS
        capabilities["encodings"] = ENCODINGS
        capabilities["encoding"] = self.encoding
        capabilities["resize_screen"] = self.randr
        if client_capabilities.get("damage_sequence", False):
            capabilities["damage_sequence"] = True
        capabilities["ping"] = True
        if "key_repeat" in client_capabilities:
            capabilities["key_repeat"] = client_capabilities.get("key_repeat")
            capabilities["key_repeat_modifiers"] = True
        capabilities["modifiers_nuisance"] = True
        if self.session_name:
            capabilities["session_name"] = self.session_name
        if self.mmap_size>0:
            capabilities["mmap_enabled"] = True
        capabilities["start_time"] = long(self.start_time)
        self._send(["hello", capabilities])

    def send_ping(self):
        if self.can_ping:
            self._send(["ping", long(1000*time.time())])

    def _process_ping_echo(self, proto, packet):
        (_, echoedtime, l1, l2, l3, sl) = packet[:6]
        diff = long(1000*time.time()-echoedtime)
        self.client_latency.append(diff)
        self.client_load = (l1, l2, l3)
        self.server_latency = sl
        log("ping echo client load=%s, measured server latency=%s", self.client_load, sl)

    def _process_ping(self, proto, packet):
        assert self.can_ping
        (_, echotime) = packet[:2]
        try:
            (fl1, fl2, fl3) = os.getloadavg()
            l1,l2,l3 = long(fl1*1000), long(fl2*1000), long(fl3*1000)
        except:
            l1,l2,l3 = 0,0,0
        cl = -1
        if len(self.client_latency)>0:
            cl = self.client_latency[-1]
        self._send(["ping_echo", echotime, l1, l2, l3, cl])
        #if the client is pinging us, ping it too:
        gobject.timeout_add(500, self.send_ping)

    def _process_set_deflate(self, proto, packet):
        level = packet[1]
        log.debug("client has requested compression level=%s", level)
        #at this point the client is sending compressed, we have enabled the decompressor
        #we echo it back to set the server's compressor and the client will set its decompressor
        self._send(["set_deflate", level])

    def disconnect(self, reason):
        if self._protocol:
            log.info("Disconnecting existing client, reason is: %s", reason)
            # send message asking for disconnection politely:
            self._protocol.source.send_packet_now(["disconnect", reason])
            self._protocol.close()
            #this ensures that from now on we ignore any incoming packets coming
            #from this connection as these could potentially set some keys pressed, etc
            if self._server_source and (self._server_source is self._protocol.source):
                self._server_source.close()
                self._server_source = None
        #so it is now safe to clear them:
        self._clear_keys_pressed()
        self._focus(0, [])
        log.info("Connection lost")
        self.close_mmap()

    def close_mmap(self):
        if self.mmap:
            self.mmap.close()
        self.mmap = None
        self.mmap_size = 0

    def _process_disconnect(self, proto, packet):
        self.disconnect("on client request")

    def _process_clipboard_enabled_status(self, proto, packet):
        (_, clipboard_enabled) = packet
        if self._clipboard_helper:
            self.clipboard_enabled = clipboard_enabled
            log.debug("toggled clipboard to %s", self.clipboard_enabled)
        else:
            log.warn("client toggled clipboard-enabled but we do not support clipboard at all! ignoring it")

    def _process_server_settings(self, proto, packet):
        (_, settings) = packet
        old_settings = dict(self._settings)
        self._settings.update(settings)
        for k, v in settings.iteritems():
            if k not in old_settings or v != old_settings[k]:
                def root_set(p):
                    prop_set(gtk.gdk.get_default_root_window(),
                             p, "latin1", v.decode("utf-8"))
                if k == "xsettings-blob":
                    self._xsettings_manager = XSettingsManager(v)
                elif k == "resource-manager":
                    root_set("RESOURCE_MANAGER")
                elif self.pulseaudio:
                    if k == "pulse-cookie":
                        root_set("PULSE_COOKIE")
                    elif k == "pulse-id":
                        root_set("PULSE_ID")
                    elif k == "pulse-server":
                        root_set("PULSE_SERVER")

    def _process_map_window(self, proto, packet):
        (_, id, x, y, width, height) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._desktop_manager.configure_window(window, x, y, width, height)
        self._desktop_manager.show_window(window)
        self._damage(window, 0, 0, width, height)

    def _process_unmap_window(self, proto, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._desktop_manager.hide_window(window)
        self._cancel_damage(window)

    def _process_move_window(self, proto, packet):
        (_, id, x, y) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        (_, _, w, h) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.configure_window(window, x, y, w, h)

    def _process_resize_window(self, proto, packet):
        (_, id, w, h) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._cancel_damage(window)
        (x, y, _, _) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.configure_window(window, x, y, w, h)
        (_, _, ww, wh) = self._desktop_manager.window_geometry(window)
        visible = self._desktop_manager.visible(window)
        log("resize_window to %sx%s, desktop manager set it to %sx%s, visible=%s", w, h, ww, wh, visible)
        if visible:
            self._damage(window, 0, 0, w, h)

    def _process_focus(self, proto, packet):
        if len(packet)==3:
            (_, id, modifiers) = packet
        else:
            modifiers = None
            (_, id) = packet
        self._focus(id, modifiers)

    def _process_layout(self, proto, packet):
        (_, layout, variant) = packet
        if layout!=self.xkbmap_layout or variant!=self.xkbmap_variant:
            self.xkbmap_layout = layout
            self.xkbmap_variant = variant
            self.set_keymap()

    def _process_keymap(self, proto, packet):
        self.xkbmap_print, self.xkbmap_query = packet[1:3]
        self.xkbmap_mod_clear, self.xkbmap_mod_add, self.xkbmap_mod_meanings = None, None, None
        self.xkbmap_mod_managed, self.xkbmap_mod_pointermissing, self.xkbmap_keycodes = None, None, None
        self.xmodmap_data, modifiers = None, []
        if len(packet)>=5:
            self.xmodmap_data, modifiers = packet[3:5]
        if len(packet)>=12:
            self.xkbmap_mod_clear, self.xkbmap_mod_add, self.xkbmap_mod_meanings, self.xkbmap_mod_managed, self.xkbmap_mod_pointermissing, self.xkbmap_keycodes = packet[5:11]
        self._make_keymask_match([])
        self.set_keymap()
        self._make_keymask_match(modifiers)


    def _keycode_from_keyname(self, keyval, keyname, modifiers):
        """ lookup a keycode based on the keyname and modifiers
            (keyval may be used if supplied - generally isn't)
        """
        level = 0
        shifted_key = keyname.startswith("Shift_")
        shift_mod = ("shift" in modifiers) or shifted_key
        caps_mod = "lock" in modifiers
        if (shift_mod or caps_mod) and not (shift_mod and caps_mod):    #xor
            level = 1
        group = 0
        #not sure this is right...
        if "meta" in modifiers:
            group = 1
        kc = self._keycode(None, keyval, keyname, group=group, level=level)
        log.info("keycode_from_name(%s,%s,%s) level=%s, group=%s, keycode=%s", keyval, keyname, modifiers, level, group, kc)
        return kc

    def _process_key_action(self, proto, packet):
        (id, keyname, pressed, modifiers) = packet[1:5]
        keyval, keycode = None, 0
        if len(packet)>=8:
            (keyval, _, client_keycode) = packet[5:8]
            keycode = self.keycode_translation.get(client_keycode, client_keycode)
        if len(packet)>=10:
            #currently unused:
            group, is_modifier = packet[8:10]
        self._focus(id, None)
        self._make_keymask_match(modifiers, keycode, ignored_modifier_keynames=[keyname])
        #negative keycodes are used for key events without a real keypress/unpress
        #for example, used by win32 to send Caps_Lock/Num_Lock changes
        if keycode>=0:
            self._handle_key(id, pressed, keyname, keyval, keycode, modifiers)

    def _handle_key(self, id, pressed, name, keyval, src_keycode, modifiers):
        """
            Does the actual press/unpress for keys
            Either from a packet (_process_key_action) or timeout (_key_repeat_timeout)
        """
        log.debug("handle_key(%s,%s,%s,%s,%s,%s)", id, pressed, name, keyval, src_keycode, modifiers)
        if pressed and (id is not None) and (id not in self._id_to_window):
            log("window %s is gone, ignoring key press", id)
            return
        if src_keycode:
            keycode = src_keycode
        else:
            keycode = self._keycode_from_keyname(keyval, name, modifiers)
            if not keycode:
                log.debug("cannot handle key action %s/%s/%s: no keycode found!", name, keyval, keycode)
                return
        if keycode in self.keys_timedout:
            del self.keys_timedout[keycode]
        def press():
            log.debug("handle keycode pressing %s: key %s", keycode, name)
            if self.keyboard_sync:
                self.keys_pressed[keycode] = name
            xtest_fake_key(gtk.gdk.display_get_default(), keycode, True)
        def unpress():
            log.debug("handle keycode unpressing %s: key %s", keycode, name)
            if self.keyboard_sync:
                del self.keys_pressed[keycode]
            xtest_fake_key(gtk.gdk.display_get_default(), keycode, False)
        if pressed:
            if keycode not in self.keys_pressed:
                press()
                if not self.keyboard_sync:
                    #keyboard is not synced: client manages repeat so unpress
                    #it immediately
                    unpress()
            else:
                log.debug("handle keycode %s: key %s was already pressed, ignoring", keycode, name)
        else:
            if keycode in self.keys_pressed:
                unpress()
            else:
                log.debug("handle keycode %s: key %s was already unpressed, ignoring", keycode, name)
        if self.keyboard_sync and keycode>0 and self.key_repeat_delay>0 and self.key_repeat_interval>0:
            self._key_repeat(id, pressed, name, keyval, src_keycode, modifiers, self.key_repeat_delay)

    def _key_repeat(self, id, pressed, keyname, keyval, keycode, modifiers, delay_ms=0):
        """ Schedules/cancels the key repeat timeouts """
        if keycode==0:
            key = keyname
        else:
            key = keycode
        timer = self.keys_repeat_timers.get(key, None)
        if timer:
            log.debug("cancelling key repeat timer: %s for %s / %s", timer, keyname, keycode)
            gobject.source_remove(timer)
        if pressed:
            delay_ms = min(1500, max(250, delay_ms))
            log.debug("scheduling key repeat timer with delay %s for %s / %s", delay_ms, keyname, keycode)
            def _key_repeat_timeout(when):
                now = time.time()
                log.debug("key repeat timeout for %s / '%s' - clearing it, now=%s, scheduled at %s with delay=%s", keyname, keycode, now, when, delay_ms)
                self._handle_key(id, False, keyname, keyval, keycode, modifiers)
                self.keys_timedout[keycode] = now
            now = time.time()
            self.keys_repeat_timers[key] = gobject.timeout_add(delay_ms, _key_repeat_timeout, now)

    def _process_key_repeat(self, proto, packet):
        if len(packet)<6:
            #don't bother trying to make it work with old clients
            if self.keyboard_sync:
                log.info("key repeat data is too small (client is too old), disabling keyboard sync")
                self.keyboard_sync = False
            return
        (id, keyname, keyval, client_keycode, modifiers) = packet[1:6]
        keycode = self.keycode_translation.get(client_keycode, client_keycode)
        #key repeat uses modifiers from a pointer event, so ignore mod_pointermissing:
        self._make_keymask_match(modifiers, ignored_modifier_keynames=self.xkbmap_mod_pointermissing)
        if not self.keyboard_sync:
            #this check should be redundant: clients should not send key-repeat without
            #having keyboard_sync enabled
            return
        if keycode not in self.keys_pressed:
            #the key is no longer pressed, has it timed out?
            when_timedout = self.keys_timedout.get(keycode, None)
            if when_timedout:
                del self.keys_timedout[keycode]
            now = time.time()
            if when_timedout and (now-when_timedout)<30:
                #not so long ago, just re-press it now:
                log.debug("key %s/%s, had timed out, re-pressing it", keycode, keyname)
                self.keys_pressed[keycode] = keyname
                xtest_fake_key(gtk.gdk.display_get_default(), keycode, True)
        self._key_repeat(id, True, keyname, keyval, keycode, modifiers, self.key_repeat_interval)

    def _process_button_action(self, proto, packet):
        (_, id, button, pressed, pointer, modifiers) = packet
        self._make_keymask_match(modifiers, ignored_modifier_keynames=self.xkbmap_mod_pointermissing)
        self._desktop_manager.raise_window(self._id_to_window[id])
        self._move_pointer(pointer)
        try:
            trap.call_unsynced(xtest_fake_button,
                               gtk.gdk.display_get_default(),
                               button, pressed)
        except XError:
            log.warn("Failed to pass on (un)press of mouse button %s"
                     + " (perhaps your Xvfb does not support mousewheels?)",
                     button)

    def _process_pointer_position(self, proto, packet):
        (_, id, pointer, modifiers) = packet
        self._make_keymask_match(modifiers, ignored_modifier_keynames=self.xkbmap_mod_pointermissing)
        if id in self._id_to_window:
            self._desktop_manager.raise_window(self._id_to_window[id])
            self._move_pointer(pointer)
        else:
            log("_process_pointer_position() invalid window id: %s", id)

    def _process_close_window(self, proto, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        window.request_close()

    def _process_shutdown_server(self, proto, packet):
        log.info("Shutting down in response to request")
        try:
            proto.close()
        except:
            pass
        self.quit(False)

    def _process_damage_sequence(self, proto, packet):
        (_, packet_sequence) = packet
        log("received sequence: %s", packet_sequence)
        self._server_source.last_client_packet_sequence = packet_sequence

    def _process_buffer_refresh(self, proto, packet):
        [id, _, jpeg_qual] = packet[1:4]
        opts = {}
        if self.encoding=="jpeg":
            opts["jpegquality"] = jpeg_qual
        if id==-1:
            windows = self._id_to_window.values()
        else:
            windows = [self._id_to_window[id]]
        log.debug("Requested refresh for windows: ", windows)
        opts["batching"] = False
        for window in windows:
            if (isinstance(window, OverrideRedirectWindowModel)):
                (_, _, w, h) = window.get_property("geometry")
            else:
                w, h = window.get_property("actual-size")
            self._damage(window, 0, 0, w, h, opts)

    def _process_jpeg_quality(self, proto, packet):
        (_, quality) = packet
        log.debug("Setting JPEG quality to ", quality)
        self._protocol.jpegquality = quality

    def _process_connection_lost(self, proto, packet):
        log.info("Connection lost")
        proto.close()
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        if proto.source and (proto.source is self._server_source):
            self._server_source.close()
            self._server_source = None
        if proto is self._protocol:
            log.info("xpra client disconnected.")
            self._clear_keys_pressed()
            self._protocol = None
            self._focus(0, [])
        sys.stdout.flush()

    def _process_gibberish(self, proto, packet):
        (_, data) = packet
        log.info("Received uninterpretable nonsense: %s", repr(data))

    _packet_handlers = {
        "hello": _process_hello,
        "server-settings": _process_server_settings,
        "map-window": _process_map_window,
        "unmap-window": _process_unmap_window,
        "move-window": _process_move_window,
        "resize-window": _process_resize_window,
        "focus": _process_focus,
        "key-action": _process_key_action,
        "key-repeat": _process_key_repeat,
        "layout-changed": _process_layout,
        "keymap-changed": _process_keymap,
        "set-clipboard-enabled": _process_clipboard_enabled_status,
        "button-action": _process_button_action,
        "pointer-position": _process_pointer_position,
        "close-window": _process_close_window,
        "shutdown-server": _process_shutdown_server,
        "jpeg-quality": _process_jpeg_quality,
        "damage-sequence": _process_damage_sequence,
        "buffer-refresh": _process_buffer_refresh,
        "desktop_size": _process_desktop_size,
        "encoding": _process_encoding,
        "ping": _process_ping,
        "ping_echo": _process_ping_echo,
        "set_deflate": _process_set_deflate,
        "disconnect": _process_disconnect,
        # "clipboard-*" packets are handled below:
        Protocol.CONNECTION_LOST: _process_connection_lost,
        Protocol.GIBBERISH: _process_gibberish,
        }

    def process_packet(self, proto, packet):
        packet_type = packet[0]
        if (isinstance(packet_type, str)
            and packet_type.startswith("clipboard-")):
            if self.clipboard_enabled:
                self._clipboard_helper.process_clipboard_packet(packet)
        else:
            self._packet_handlers[packet_type](self, proto, packet)

gobject.type_register(XpraServer)
