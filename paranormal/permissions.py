"""Public CoreFoundation bundle checks before asking macOS privacy consent."""
import ctypes
import sys


def usage_declared(name):
    if sys.platform != 'darwin':
        return True
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cf.CFBundleGetMainBundle.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFBundleGetValueForInfoDictionaryKey.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cf.CFBundleGetValueForInfoDictionaryKey.restype = ctypes.c_void_p
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    key = cf.CFStringCreateWithCString(None, name.encode(), 0x08000100)
    try:
        bundle = cf.CFBundleGetMainBundle()
        return bool(bundle and cf.CFBundleGetValueForInfoDictionaryKey(bundle, key))
    finally:
        cf.CFRelease(key)
