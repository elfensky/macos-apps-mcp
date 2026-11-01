"""G2 probe: which AX error code does an UNTRUSTED process get, per kind of element?
Reads only (AXFrontmost / AXRole of the Finder application element, AXFocusedUIElement of
the system-wide element). Run as a plain process. Mail is never touched."""
import ctypes, subprocess
HI = "/System/Library/Frameworks/ApplicationServices.framework/Frameworks/HIServices.framework/HIServices"
CF = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
hi, cf = ctypes.CDLL(HI), ctypes.CDLL(CF)
hi.AXIsProcessTrusted.restype = ctypes.c_bool
hi.AXUIElementCreateSystemWide.restype = ctypes.c_void_p
hi.AXUIElementCreateApplication.restype = ctypes.c_void_p
hi.AXUIElementCreateApplication.argtypes = [ctypes.c_int]
hi.AXUIElementCopyAttributeValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
hi.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
cf.CFStringCreateWithCString.restype = ctypes.c_void_p
cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
def attr(name): return cf.CFStringCreateWithCString(None, name.encode(), 0x08000100)
pid = int(subprocess.run(["pgrep", "-x", "Finder"], capture_output=True, text=True).stdout.split()[0])
print("trusted:", bool(hi.AXIsProcessTrusted()))
for label, el, name in (
    ("system-wide AXRole", hi.AXUIElementCreateSystemWide(), "AXRole"),
    ("system-wide AXFocusedUIElement", hi.AXUIElementCreateSystemWide(), "AXFocusedUIElement"),
    ("Finder app AXFrontmost", hi.AXUIElementCreateApplication(pid), "AXFrontmost"),
    ("Finder app AXRole", hi.AXUIElementCreateApplication(pid), "AXRole"),
):
    out = ctypes.c_void_p()
    print(f"{label:<32} -> {hi.AXUIElementCopyAttributeValue(el, attr(name), ctypes.byref(out))}")
