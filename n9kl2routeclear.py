# Python3@Nexus

"""
n9kl2routeclear.py

Copyright (C) 2021 NIX.CZ, z.s.p.o.
Author: Tomas Hlavacek (tomas.hlavacek@nix.cz)

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.
"""

# This script runs in the emdedded Python3 interpreter in Cisco Nexus 9300 series
# switches and is tested with NX-OS 9.3.
#
# The script clears the MAC conflicts between EVPN-supplied secure (sticky) MAC
# addresses and the locally-learned MAC addresses from physical (non-secure) ports,
# should such a conflict occur.
#
# The script that should be run from EEM (embedded event manager) on NX-OS 9.3 on
# Nexus 9300 series when a conflict between secure (sticky) MAC address recevied
# and learned over EVPN and locally learned (unsecure) MAC occurs. There are
# apparently multuiple bugs/"features" that causes:
# 1) the local MAC address is allowed to MAC address table and learned locally,
# 2) the locally learned (supposedly unsecure and therefore non-sticky) MAC address
# overrides the sticky EVPN-origined address and
# 3) the locally-learned address sticks (is kept forever) even though there is no
# reason for that.
#    
# Since the aging timer seems not to apply to the locally-learned MAC that overriden
# sticky EVPN-orinigated MAC and there is usually no reason for EVPN to signal any
# change on the secure EVPN-origin address, the switch in question keeps the unsecure
# locally-learned address forever (until reboot, manual clear of the MAC or perhaps
# explicit signaling from EVPN side).
#
# The good news is that the conflict produces a distinct log message that contains the
# information needed to resovle the situation. We choose the approach that when such
# log message appears, we let the EEM run our script that waits for 10 seconds and then
# clears all the conflict it finds since the last run of the script. For that the script
# keeps track of the history.
#
# The script could be started by the following EEM configuration:
#
#  event manager applet macconflict
#    event syslog pattern "%L2RIB-2-L2RIB_LOCAL_LEARNT_MAC_PRESENT_AS_REMOTE_STATIC"
#    action 1 cli python3 bootflash:///n9kl2routeclear.py


debug = True
dry_run = False
statefile='/volatile/macconflict.json'
logfile = '/log/messages'
lockfile = '/volatile/macconflict.lock'
initdelay = 10 # seconds

import re
import os
import json
import datetime
import cisco
import time
import syslog
import sys
import fcntl
import errno
import hashlib


def d(msg):
  if debug:
    try:
      bfn = sys.argv[0].split('/')[-1].strip()
    except:
      bfn = '???'

    syslog.syslog(syslog.LOG_ERR, f"{bfn} ({os.getpid()}) {msg}")
    print(msg)

  if True:
    with open('/volatile/macconflict.log', 'a') as fd:
      fd.write(f"{datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')} ({os.getpid()}) {msg}\n")


def lock(filename=lockfile):
  fh = open(filename, "w+")
  try:
    fcntl.flock(fh, fcntl.LOCK_EX|fcntl.LOCK_NB)
    d(f"acquired lock {filename}")
    return fh
  except IOError as e:
    if e.errno not in [errno.EACCES, errno.EAGAIN]:
      raise e
    else:
      d(f"can not acquire lock {filename}")
      return None


def unlock(lockfh, filename=lockfile):
  fcntl.flock(lockfh, fcntl.LOCK_UN)
  os.unlink(filename)
  d(f"released lock {filename}")


def loadstate(filename=statefile):
  if os.path.exists(filename):
    try:
      with open(filename, 'r') as fd:
        return json.loads(fd.read())
    except:
      return {}
  else:
      return {}


def savestate(state, filename=statefile):
  with open(filename, 'w') as fd:
    fd.write(json.dumps(state))



#0c6 2021 Aug  2 14:02:30 GX %L2RIB-2-L2RIB_LOCAL_LEARNT_MAC_PRESENT_AS_REMOTE_STATIC: Locally learnt MAC 00e0.4c3d.269f in topology: 999 already present as remote static
#There is Cisco specific string on beginning of each log record - in this case it is '#0c6'

conflictre = re.compile(r"([0-9a-z]+)\s+([0-9]+\s+[A-Za-z]+\s+[0-9]+\s+[0-9:\.]+)\s+[^\s]+\s+%L2RIB-2-L2RIB_LOCAL_LEARNT_MAC_PRESENT_AS_REMOTE_STATIC: Locally learnt MAC\s+([0-9a-f\.]+)\s+in topology:\s+([0-9]+)\s+already present as remote static.*")

def parselog(state, filename=logfile):
  with open(filename, 'r') as fd:
    fls = hashlib.md5(fd.readline().encode()).hexdigest()

    fd.seek(0, os.SEEK_END)
    if state.get('offset', 0) < fd.tell() and state.get('firstlinesum', '') == fls:
      fd.seek(state.get('offset', 0))
    else:
      fd.seek(0)
    d(f"Reading the log {filename} from offset {fd.tell()}")

    for l in fd.readlines():
      m = conflictre.match(l.strip())
      if m:
        lid, ltime, mac, vlan = m.groups()    
        ts = datetime.datetime.strptime(ltime, "%Y %b %d %H:%M:%S").timestamp()
        if (ts >= state.get('lasttime', 0)-10):
          yield (lid, ltime, ts, mac, vlan)
          state['lasttime'] = ts

    state['offset'] = fd.tell()
    state['firstlinesum'] = fls
    d(f"The log file {filename} leaved at offset {state['offset']}")


def main():
  d(f"script running")

  # The critical section is the waiting: We expect the EEM to trigger one or multiple
  # times in a short burst, in this case we run the script just once; after the waiting
  # time we first unlock, so another instance of the script can be started while we
  # read the log file and clear the conflicts, but the new instance will go to waiting
  # state first and we assume that the waiting period is going to be longer that log
  # parsing and cleanup.
  # If the conflict for one or more MAC addresses persists, we expect to see the
  # same log message over and over just after we clear the MAC record. It is fine,
  # we let the script run once in waiting mode while the last instance that cleared
  # the offending MAC(s) few moments ago is finishing. This should lead to a new
  # attempt to clear the offending MAC address(es) after the predefined delay over and
  # over again until the conflict is resolved.

  lfh = lock()
  if not lfh:
    d("script halted due to locking")
    sys.exit(1)

  d(f"script waiting for timer ({initdelay} sec)")
  time.sleep(initdelay)
  unlock(lfh)

  # following code is not the critical part, any concurrency hazard can cause more
  # executions of the resulting Cisco CLI call, so it is "at-least-once" execution,
  # which is what we desire
  state = loadstate()

  clearset = set()
  for lid, ltime, ts, mac, vlan in parselog(state):
    d(f"Considering MAC for record: time={ltime} ({ts}), mac={mac} vlan={vlan}")
    clearset.add((mac, vlan))

  for mac, vlan in clearset:
    if dry_run:
      d(f"Dry run: Clearing MAC {mac} for vlan {vlan}")
    else:
      d(f"Clearing MAC {mac} for vlan {vlan}")
      res = cisco.nxos_cli.nxcli(f"clear mac address-table dynamic address {mac} vlan {vlan}")
      d(f"CLI call result: {res}")

  savestate(state)
  d(f"script finished")

if __name__ == '__main__':
  main()
