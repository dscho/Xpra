# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import traceback
import sys

def dump_exc():
    """Call this from a except: clause to print a nice traceback."""
    print("".join(traceback.format_exception(*sys.exc_info())))

# A simple little class whose instances we can stick random bags of attributes
# on.
class AdHocStruct(object):
    def __repr__(self):
        return ("<%s object, contents: %r>"
                % (type(self).__name__, self.__dict__))


class AtomicInteger(object):
    def __init__(self, integer = 0):
        self.counter = integer
        self.lock = threading.RLock()

    def increase(self, inc = 1):
        self.lock.acquire()
        self.counter = self.counter + inc
        v = self.counter
        self.lock.release()
        return v

    def decrease(self, dec = 1):
        self.lock.acquire()
        self.counter = self.counter - dec
        v = self.counter
        self.lock.release()
        return v

    def get(self):
        return self.counter

    def __str__(self):
        return str(self.counter)

def alnum(_str):
    return filter(str.isalnum, _str)

def nn(x):
    if x is None:
        return  ""
    return x

def nonl(x):
    if x is None:
        return None
    return str(x).replace("\n", "\\n").replace("\r", "\\r")
