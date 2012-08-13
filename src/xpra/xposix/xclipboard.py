# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct

from wimpiggy.lowlevel import (gdk_atom_objects_from_gdk_atom_array, #@UnresolvedImport
                               gdk_atom_array_from_gdk_atom_objects) #@UnresolvedImport

from xpra.platform.clipboard_base import ClipboardProtocolHelperBase, debug

class ClipboardProtocolHelper(ClipboardProtocolHelperBase):
    """ This clipboard helper adds the ability to parse raw X11 atoms
        to and from a form suitable for transport over the wire.
    """

    def __init__(self, send_packet_cb):
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, ["CLIPBOARD", "PRIMARY", "SECONDARY"])

    def _do_munge_raw_selection_to_wire(self, target, dtype, dformat, data):
        if dformat == 32 and dtype in ("ATOM", "ATOM_PAIR"):
            # Convert to strings and send that. Bizarrely, the atoms are
            # not actual X atoms, but an array of GdkAtom's reinterpreted
            # as a byte buffer.
            atoms = gdk_atom_objects_from_gdk_atom_array(data)
            atom_names = [str(atom) for atom in atoms]
            if target=="TARGETS":
                otargets = list(atom_names)
                discard_targets = ("SAVE_TARGETS", "COMPOUND_TEXT")
                for x in discard_targets:
                    if x in atom_names:
                        atom_names.remove(x)
                debug("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s) filtered targets(%s)=%s", target, dtype, dformat, type(data), len(data), otargets, atom_names)
            return ("atoms", atom_names)
        return ClipboardProtocolHelperBase._do_munge_raw_selection_to_wire(self, target, dtype, dformat, data)

    def _munge_wire_selection_to_raw(self, encoding, dtype, dformat, data):
        debug("_munge_wire_selection_to_raw(%s, %s, %s, %s:%s:%s)", encoding, dtype, dformat, type(data), len(data or ""), list(data or ""))
        if encoding == "atoms":
            import gtk.gdk
            gdk_atoms = [gtk.gdk.atom_intern(a) for a in data]
            atom_array = gdk_atom_array_from_gdk_atom_objects(gdk_atoms)
            bdata = struct.pack("=" + "Q" * len(atom_array), *atom_array)
            debug("_munge_wire_selection_to_raw(%s, %s, %s, %s:%s)=%s=%s=%s", encoding, dtype, dformat, type(data), len(data or ""), gdk_atoms, atom_array, list(bdata))
            return bdata
        return ClipboardProtocolHelperBase._munge_wire_selection_to_raw(self, encoding, dtype, dformat, data)

