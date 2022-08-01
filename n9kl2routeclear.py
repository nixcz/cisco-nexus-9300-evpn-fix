# Python3@Nexus

#
# Copyright (C) 2022 NIX.CZ, z.s.p.o.
# Author: Radek Senfeld (radek.senfeld@nix.cz)
# Co-Author: Tomas Hlavacek (tomas.hlavacek@nix.cz)
#
# Cisco EEM configuration is as follows:
#
#  event manager applet macconflict
#    event syslog pattern "%L2RIB-2-L2RIB_LOCAL_LEARNT_MAC_PRESENT_AS_REMOTE_STATIC"
#    action 1 cli python3 bootflash:///n9kl2routeclear.py $_syslog_msg
#

import re
import sys
import cisco
import syslog

# %L2RIB-2-L2RIB_LOCAL_LEARNT_MAC_PRESENT_AS_REMOTE_STATIC: Locally learnt MAC 00e0.4c3d.269f in topology: 999 already present as remote static
re_conflict = re.compile(r"%L2RIB-2-L2RIB_LOCAL_LEARNT_MAC_PRESENT_AS_REMOTE_STATIC: Locally learnt MAC\s+(?P<mac>[0-9a-f\.]+)\s+in topology:\s+(?P<vlan>[0-9]+)\s+already present as remote static")

#
def log(msg):
	syslog.syslog(syslog.LOG_ERR, msg)


if __name__ == "__main__":
	try:
		msg = " ".join(sys.argv[1:])

		m = re_conflict.match(msg.strip())
		if m:
			mac = m.group("mac")
			vlan = m.group("vlan")

			log(f"Clearing MAC {mac} for VLAN {vlan}")
			res = cisco.nxos_cli.nxcli(f"clear mac address-table dynamic address {mac} vlan {vlan}")
			log(f"CLI call result: {res}")
		else:
			log("No match found")
	except IndexError:
		log("No syslog message received..")
		sys.exit(1)
