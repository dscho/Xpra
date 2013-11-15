# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.platform.keyboard_base import KeyboardBase
from xpra.log import Logger
log = Logger()

NUM_LOCK_KEYCODE = 71           #HARDCODED! 


class Keyboard(KeyboardBase):

    def __init__(self):
        self.num_lock_modifier = None
        self.num_lock_state = True
        self.num_lock_keycode = NUM_LOCK_KEYCODE

    def set_modifier_mappings(self, mappings):
        KeyboardBase.set_modifier_mappings(self, mappings)
        self.num_lock_modifier = self.modifier_keys.get("Num_Lock")

    def mask_to_names(self, mask):
        names = KeyboardBase.mask_to_names(self, mask)
        if self.num_lock_modifier is not None:
            if self.num_lock_state and self.num_lock_modifier not in names:
                names.append(self.num_lock_modifier)
            elif not self.num_lock_state and self.num_lock_modifier in names:
                names.remove(self.num_lock_modifier)
        log("mask_to_names(%s)=%s", mask, names)
        return names

    def process_key_event(self, send_key_action_cb, wid, key_event):
        if key_event.keycode==self.num_lock_keycode and not key_event.pressed:
            log("toggling numlock")
            self.num_lock_state = not self.num_lock_state
        send_key_action_cb(wid, key_event)

