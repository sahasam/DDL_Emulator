"""
port.py

Represent a single terminal of the emulated network. One port represents one port thread on a machine,
and handles raw packets asynchronously from the rest of the system. The port abstraction allows the
emulation to manually inject all different types of faults as present in clos networks or perr-to-peer links.
"""

