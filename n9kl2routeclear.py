# Python3@Nexus

import re
import sys
import cisco
import syslog

# 2022 Aug  1 13:18:51 LAB2-S1 %L2RIB-2-L2RIB_LOCAL_LEARNT_MAC_PRESENT_AS_REMOTE_STATIC: Locally learnt MAC 00e0.4c3d.269f in topology: 999 already present as remote static
re_conflict = re.compile(r"(?P<timestamp>[0-9]+\s+[A-Za-z]+\s+[0-9]+\s+[0-9:\.]+)\s+[^\s]+\s+%L2RIB-2-L2RIB_LOCAL_LEARNT_MAC_PRESENT_AS_REMOTE_STATIC: Locally learnt MAC\s+(?P<mac>[0-9a-f\.]+)\s+in topology:\s+(?P<vlan>[0-9]+)\s+already present as remote static.*")

#
def log(msg):
	syslog.syslog(syslog.LOG_ERR, msg)


if __name__ == "__main__":
	try:
		msg = " ".join(sys.argv[1:])

		m = re_conflict.match(msg.strip())
		if m:
			# timestamp = m.group("timestamp")
			mac = m.group("mac")
			vlan = m.group("vlan")

			log(f"Clearing MAC {mac} for VLAN {vlan}")
			res = cisco.nxos_cli.nxcli(f"clear mac address-table dynamic address {mac} vlan {vlan}")
			log(f"CLI call result: {res}")
	except IndexError:
		log("No syslog message received.. :-(")
		sys.exit(1)
