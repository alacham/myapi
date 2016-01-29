# -*- coding: utf-8 -*-
from __future__ import division
#
import sys
# reload(sys)
# sys.setdefaultencoding('utf8')

import os
import psycopg2
import psycopg2.extras
# psycopg2.extras.register_default_json(loads=lambda x: x)
import time
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import re
import random
import string
import json
import time
import threading
import pprint
import copy
import requests
import hashlib
import binascii
import logging
import Queue


from cloud_api_settings import *
from cloud_api_nebulaconstants import *
from datetime import datetime, timedelta



logging.basicConfig(filename=LOGGING_PATH, level=LOGLEVEL)



def totimestamp(dt, epoch=datetime(1970, 1, 1)):
    td = dt - epoch
    # return td.total_seconds()
    return (td.microseconds + (td.seconds + td.days * 86400) * 10 ** 6) / 10 ** 6



tdata = threading.local()  # thread local data - mainly for username
tdata.extended_error_log = []
tdata.user_info = []
tdata.DB_CON = None


def modified_pformat(arg):
    if isinstance(arg, basestring):
        return arg
    else:
        return pprint.pformat(arg)


def debug_log(*args):
    now = str(datetime.utcnow())

    if isinstance(args[0], basestring):
        topr = now + ": "
    else:
        topr = now + ":\n"
    topr += "\n".join(map(modified_pformat, args))
    logging.debug(topr)


def debug_print(*args):
    now = str(datetime.utcnow())

    if isinstance(args[0], basestring):
        topr = now + ": "
    else:
        topr = now + ":\n"
    topr += "\n".join(map(modified_pformat, args))
    if DEBUG_PRINTS:
        print topr


def debug_log_print(*args):
    now = str(datetime.utcnow())

    if isinstance(args[0], basestring):
        topr = now + ": "
    else:
        topr = now + ":\n"
    topr += "\n".join(map(modified_pformat, args))
    logging.debug(topr)
    if DEBUG_PRINTS:
        print topr


def debug_log_print_ext(*args):
    now = str(datetime.utcnow())

    if isinstance(args[0], basestring):
        topr = now + ": "
    else:
        topr = now + ":\n"
    topr += "\n".join(map(modified_pformat, args))
    logging.debug(topr)
    tdata.extended_error_log.append(topr)
    if DEBUG_PRINTS:
        print topr

def add_to_user_problem_msg(*msgs):
    for msg in msgs:
        tdata.user_info.append(msg)

def get_user_problem_msg():
    return "\n".join(tdata.user_info)


callback_send_queue = Queue.Queue()

callbacks_in_queue = Queue.Queue()

NODES_INFO = {}
NETS_INFO = {}

debug_log_print("init")
nodes_info_lock = threading.Lock()
nodes_info_lock.acquire()

nets_info_lock = threading.Lock()
nets_info_lock.acquire()

CALLBACKCHECK_CONDITON = threading.Condition()


class InfoPoller(threading.Thread):
    def run(self):

        global NODES_INFO
        global NETS_INFO

        NODES_INFO = self.list_nodes_nebula()
        # debug_log_print(NODES_INFO)
        nodes_info_lock.release()
        NETS_INFO = self.list_nebulanets_xml()
        nets_info_lock.release()

        time.sleep(2)

        # main checking loop
        while True:
            nodes = self.list_nodes_nebula()
            nodes_info_lock.acquire()
            NODES_INFO = nodes
            nodes_info_lock.release()
            with CALLBACKCHECK_CONDITON:
                CALLBACKCHECK_CONDITON.notifyAll()

            time.sleep(1)

            nets = self.list_nebulanets_xml()
            nets_info_lock.acquire()
            NETS_INFO = nets
            nets_info_lock.release()

            time.sleep(1)

    @staticmethod
    def list_nodes_nebula():
        try:
            out, stderr = run_cmd_e("onevm list -x")
            tree = ET.fromstring(out)

            # root = tree.getroot()
            vms = {}
            for vm in tree:
                k, val = recursive_element_list(vm)
                nid = val['ID']

                v = val.get("TEMPLATE")
                if v:
                    if not v.get("NIC"):
                        v["NIC"] = []
                    elif not isinstance(v['NIC'], list):
                        v["NIC"] = [v["NIC"]]

                    if not v.get("DISK"):
                        v["DISK"] = []
                    elif not isinstance(v["DISK"], list):
                        v["DISK"] = [v["DISK"]]

                    if not v.get('HISTORY_RECORDS'):
                        v['HISTORY_RECORDS'] = []
                    elif not isinstance(v['HISTORY_RECORDS'], list):
                        v['HISTORY_RECORDS'] = [v['HISTORY_RECORDS']]

                vms[nid] = val
        except ExternalCMDError as e:
            debug_log_print(e)
            return {}
        return vms

    @staticmethod
    def list_nebulanets_xml():
        try:
            out, stderr = run_cmd_e("onevnet list -x")
            tree = ET.fromstring(out)

            # root = tree.getroot()
            vnets = {}
            for vnet in tree:
                k, v = recursive_element_list(vnet)
                nid = v['ID']

                # ars_d = {} #address ranges
                if v['AR_POOL'] is not None:
                    if isinstance(v['AR_POOL']['AR'], list):
                        v['AR_POOL'] = v['AR_POOL']['AR']

                    else:
                        v['AR_POOL'] = [v['AR_POOL']['AR']]

                    for v2 in v['AR_POOL']:
                        if v2.get("ALLOCATED"):  # is not None nor empty dict
                            allocated = map(int, v2["ALLOCATED"].split())
                            alloc_d = {}

                            for i in range(0, int(len(
                                    allocated) / 2)):  # TODO to int by melo byt zbytecne, ale kvuli nejakemu bugu neni
                                # viz binary_magic = 0x0000001000000000 | (vid & 0xFFFFFFFF)
                                # v https://github.com/burgosz/opennebula-sunstone-shib/blob/master/ruby/onedb/local/4.5.80_to_4.7.80.rb
                                alloc_d[allocated[i * 2]] = allocated[i * 2 + 1] & 0x00000000FFFFFFFF
                            v2["ALLOCATED"] = alloc_d
                        else:
                            v2["ALLOCATED"] = {}

                else:
                    v['AR_POOL'] = []

                vnets[nid] = v
        except RuntimeError as e:
            debug_log_print(e)
            return {}
        return vnets


class CallbackDispatcher(threading.Thread):
    def run(self):

        while True:

            tosend = callback_send_queue.get()

            r = requests.post(tosend["url"], json=tosend["data"])

            if r.status_code != 200:
                debug_log_print("Error sending callback", tosend)

            callback_send_queue.task_done()


class CallbackChecker(threading.Thread):
    def run(self):

        callbacks_to_check = []
        resend_notify_signal = []

        nodes = list_nodes_nebula()

        with CALLBACKCHECK_CONDITON:
            while True:
                # obtain new hooks from queue
                while True:
                    try:
                        callback = callbacks_in_queue.get_nowait()
                        callbacks_to_check.append(callback)
                    except Queue.Empty:
                        break

                newcallbacks = []
                for callback in callbacks_to_check:
                    should_notify = callback.check_changes(nebuladict=nodes)
                    if should_notify:
                        if callback.notifycondition:
                            resend_notify_signal.append(callback.notifycondition)

                    if not callback.finished:
                        newcallbacks.append(callback)
                    else:
                        callback.destructor()

                callbacks_to_check = newcallbacks

                ## wait for signal to check
                # debug_log_print("zzzzzzz...")
                CALLBACKCHECK_CONDITON.wait()
                nodes = list_nodes_nebula()

                while True:
                    try:
                        condition = resend_notify_signal.pop()
                        with condition:
                            condition.notifyAll()
                    except IndexError:
                        break


class MacAddress(object):
    def __init__(self, macplainstr):
        self.nummeric = int(macplainstr, 16)

    def __str__(self):
        plainstr = '%012x' % self.nummeric
        outstr = []
        maclen = len(plainstr)
        for i in range(maclen):
            outstr.append(plainstr[i])
            if i % 2 == 1 and i != maclen - 1:
                outstr.append(":")
        return "".join(outstr)

    def __repr__(self):
        return self.__str__()

    @classmethod
    def from_parts(cls, macprefix=None, macsuffix=None, delim=":"):
        if macprefix:
            macprefix = macprefix.replace(delim, "")
        else:
            macprefix = MAC_PREFIX_DEFAULT.replace(delim, "")
        if macsuffix:
            macsuffix = macsuffix.replace(delim, "")
        else:
            macsuffix = ""

        togen = 12 - (len(macprefix) + len(macsuffix))
        macmiddle = "".join(random.choice('0123456789abcdef') for _ in range(togen))

        # TODO check for duplicates

        macplain = macprefix + macmiddle + macsuffix

        macobj = MacAddress(macplain)

        return macobj

    @classmethod
    def from_delimited(cls, macstr, delim=":"):
        parts = macstr.split(delim)
        if len(parts) != 6:
            raise BadMacAddrException
        try:
            for p in parts:
                if not 0 <= int(p, base=16) <= 255:
                    raise BadMacAddrException
        except:
            raise BadMacAddrException
        return MacAddress(macstr.replace(delim, ""))

    @classmethod
    def from_nummeric(cls, num):
        """

        :param num: ninteger representing mac addr
        :return: macaddress formatted as hexadecimal without ':'
        """
        plainstr = '%012x' % num
        return MacAddress(plainstr)


class GeneralAPIError(Exception):
    def __init__(self, arg=""):
        self.message = arg


class ExternalCMDError(GeneralAPIError):
    pass


class WrongRequestException(GeneralAPIError):
    pass


class DuplicateNameException(GeneralAPIError):
    pass


class NoSuchObjectException(GeneralAPIError):
    pass


class BadMacAddrException(GeneralAPIError):
    pass


class PrivilegeException(GeneralAPIError):
    pass


class WrongStateForActionException(GeneralAPIError):
    pass


# for waiting for event to give up after certain time
def try_more_time(start_time, max_time):
    """

    :param start_time:
    :param max_time:
    :return:
    """
    if max_time == 0:
        return True

    if (time.time() - start_time) > max_time:
        return False
    else:
        return True


class NotifyTask(object):
    active_hooks = {}

    def __init__(self, node_ids=None, change_selector=None, towhat=None, howmany=0, howlong=0, notifycondition=None,
                 notifyaddr=None, userhook=False):
        self.user = tdata.username
        self.inittime = datetime.utcnow()
        self.finished = False
        self.towhat = towhat
        self.change_selector = change_selector
        self.howmany = howmany
        self.counter = 0
        self.howlong = howlong
        self.notifycondition = notifycondition
        self.notifyaddr = notifyaddr

        self.nebulaidstocheck = set()
        self.openstackidstocheck = set()

        self.nebulaid_2_dbid = {}
        self.ostackid_2_dbid = {}
        if node_ids:
            for nid in node_ids:

                try:
                    nodeinfo = get_node_db(nid)
                except NoSuchObjectException:
                    debug_log_print("notifytask: Entered Id doesn't belong to any id")
                    add_to_user_problem_msg("Entered node id doesn't return any match")
                    if userhook:
                        raise
                    continue

                try:
                    if nodeinfo["platform"] == "nebula" and nodeinfo["internal_id"]:
                        self.nebulaidstocheck.add(nodeinfo["internal_id"])
                        self.nebulaid_2_dbid[nodeinfo["internal_id"]] = nid
                    else:  # TODO OpenStack
                        pass
                except Exception as e:
                    debug_log_print("NotifyTask: get internal id error: " + e)

        while True:
            self.taskid = random.randint(0, 2 ** 32 - 1)
            if not self.taskid in self.active_hooks.keys():
                self.active_hooks[self.taskid] = self
                break

        if (not self.nebulaidstocheck and not self.openstackidstocheck) or (
                    not notifycondition and not notifyaddr) or not self.change_selector:
            self.finished = True
        else:
            if self.nebulaidstocheck:
                self.previous_nebula = {}

    """
        checks if there are matching changes and possibly notifies about it
        :returns True to signal that it's to safe discard this check, False otherwise
    """

    def check_nebulanodes_changes(self, current_nebuladict):
        """

        :param current_nebuladict:
        :return:
        """
        changes_n = {}
        if self.finished:
            if self.notifycondition:
                with self.notifycondition:
                    self.notifycondition.notifyAll()
            return True

        idstoremove = set()
        for nebulaid in self.nebulaidstocheck:

            try:
                curval = current_nebuladict[nebulaid][self.change_selector]

            except KeyError:
                debug_log("nebulaid %d or field selector %s not found" % (nebulaid, str(self.change_selector)))
                changes_n[self.nebulaid_2_dbid[nebulaid]] = "nonexistent"
                idstoremove.add(nebulaid)
                continue

            prevnodestate = self.previous_nebula.get(nebulaid, {})
            prevval = prevnodestate.get(self.change_selector, None)

            if prevval == curval:
                continue

            if curval == self.towhat or self.towhat is None:
                changes_n[self.nebulaid_2_dbid[nebulaid]] = curval

        self.previous_nebula = current_nebuladict
        self.nebulaidstocheck.difference_update(idstoremove)

        if changes_n:
            if self.notifycondition:
                with self.notifycondition:
                    self.notifycondition.notifyAll()
            if self.notifyaddr:
                datamsg = {"status": "ok", "type": "callback update", "changes": changes_n, "callbackid": self.taskid}
                callback_send_queue.put({"url": self.notifyaddr, "data": datamsg})
            self.counter += 1
            if self.howmany and self.counter >= self.howmany:
                self.finished = True
            return True

        curtime = datetime.utcnow()
        if self.howlong and totimestamp(self.inittime) + self.howlong >= totimestamp(curtime):

            if self.notifycondition:
                with self.notifycondition:
                    self.notifycondition.notifyAll()
            if self.notifyaddr:
                datamsg = {"status": "error", "type": "callback timeout", "callbackid": self.taskid}

                callback_send_queue.put({"url": self.notifyaddr, "data": datamsg})
            self.finished = True

            return True
        return False

    def check_openstacknodes_changes(self, current_openstackdict):
        # self.changes_o = {}
        return False

    def check_changes(self, nebuladict=None, openstackdict=None):
        return self.check_nebulanodes_changes(nebuladict) or self.check_openstacknodes_changes(openstackdict)

    @classmethod
    def get_all_hooks(cls):
        return [ h.as_repr_dict() for h in cls.active_hooks ]


    def as_repr_dict(self):
        res = {}

        res["username"] = self.username
        res["starttime"] = self.inittime
        res["isfinished"] = self.finished
        res["goalstate"] = self.towhat
        res["selector"] = self.change_selector

        res["node_ids"] = self.nebulaid_2_dbid.values() + self.ostackid_2_dbid.values()
        if self.howlong:
            res["endtime"] = str(totimestamp(self.inittime) + self.howlong)
        else:
            res["endtime"] = None
        res["notify_address"] = self.notifyaddr
        res["id"] = self.taskid

        return res

    def destructor(self):
        try:
            del self.active_hooks[self.taskid]
        except (AttributeError, KeyError):
            pass
        self.finished = True



# def check_condition(test_callable, test_args, check_result_function, check_args, reaction, max_attempt_time, once=False):
#
# def testfunction():
# starttime = time.time()
#         end_condition = False
#
#         while end_condition == False and try_more_time(starttime, max_attempt_time):
#             results = test_callable(**test_args)
#
#             end_condition = check_result_function(results, **check_args)
#
#
#     return testfunction

def check_user_privilege_node(nodeid, username=None):
    """

    :param nodeid:
    :type nodeid:
    :param username:
    :type username:
    :return:
    :rtype:
    """
    if not username:
        if tdata.isadmin:
            return True
        username = tdata.username
    tags = get_tags_node(nodeid)
    usertag = "owner:{0}".format(username)
    if usertag not in tags:
        add_to_user_problem_msg("you are neither admin, nor owner of this node")
        add_to_user_problem_msg("Legitimate users:", str(filter(lambda a: a.startswith("owner:"), tags)))
        raise PrivilegeException("{0} is not owner of this node".format(username))


def check_user_privilege_net(netid, username=None):
    """

    :param netid:
    :type netid:
    :param username:
    :type username:
    :return:
    :rtype:
    """
    if not username:
        if tdata.isadmin:
            return True
        username = tdata.username
    tags = get_tags_net(netid)
    usertag = "owner:{0}".format(username)
    if usertag not in tags:
        add_to_user_problem_msg("you are neither admin, nor owner of this net")
        add_to_user_problem_msg("Legitimate users:", str(filter(lambda a: a.startswith("owner:"), tags)))
        raise PrivilegeException("{0} is not owner of this net".format(username))


def run_cmd(cmd):
    """

    :param cmd:
    :type cmd:
    :return:
    :rtype:
    """
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    stdout, stderr = process.communicate()

    if process.returncode != 0:
        return stderr + stdout, stderr
    return stdout, stderr


def run_cmd_e(cmd):
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    stdout, stderr = process.communicate()

    if process.returncode:
        raise ExternalCMDError("Error executing '{0}': \nSTDOUT: {1}\nSTDERR: {2}".format(cmd, stdout, stderr))
    return stdout, stderr

def run_cmd_with_ret(cmd):
    """

    :param cmd:
    :type cmd:
    :return:
    :rtype:
    """
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    stdout, stderr = process.communicate()

    return process.returncode, stdout, stderr

# vulnerability, replace with paramiko module
def run_ssh_on_node(nodeid, cmd):
    check_user_privilege_node(nodeid)

    base_ssh_cmd = "ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -A root@{0} {1}"

    ip_addrs = filter(None, map(lambda a: a["ip_addr"], get_accessible_intf(nodeid)))

    #TODO: zkusim proste prvni - jake jine moznosti reseni?

    cmd_to_exec = base_ssh_cmd.format(ip_addrs[0], base_ssh_cmd)

    result = {}
    result["exit_status"], result["stdout"], result["stderr"] = run_cmd_with_ret(cmd_to_exec)

    return result



def get_accessible_intf(nodeid):
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        db_cur.execute("SELECT intf.* from interfaces intf, networks net WHERE \
          net.type='plain-flat' AND net.id=intf.net_id AND intf.node_id=%s  AND (net.vid IS NULL OR net.vid=0) ;", (nodeid,))
        ip_addrs = db_cur.fetchone()
    return ip_addrs


def open_db2():
    debug_log_print("trying to connect database: ", (DATABASE, DBUSER))
    try:
        db_con = psycopg2.connect(database=DATABASE, user=DBUSER)
        db_con.autocommit = True
    except psycopg2.DatabaseError as e:
        debug_log_print(repr(e))
        raise

    return db_con


def get_network_db(netid):
    check_user_privilege_net(netid)
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        db_cur.execute("SELECT * from networks WHERE id = %s ;", (netid,))
        net_dict = db_cur.fetchone()
    if not net_dict:
        raise NoSuchObjectException("no such network id: {0}".format(netid))

    return net_dict


def get_network_db_and_internal(netid):
    net_d = get_network_db(netid)
    internalid = net_d["nebulaid"]
    try:
        net_d["internal_info"] = info_nebulanet(internalid)
    except NoSuchObjectException:
        net_d["internal_info"] = None

    return net_d


def get_network_db_for_output(netid):
    net_d = get_network_db(netid)
    internalid = net_d["nebulaid"]
    internalinfo = info_nebulanet(internalid)
    net_d["used_leases"] = internalinfo["USED_LEASES"]
    return net_d


def get_nodes_db_and_internal(tags=None, nodeids=None):
    nodes_d = get_nodes_db(tags, nodeids)

    nebulanodes = list_nodes_nebula()

    for node in nodes_d.values():
        internalid = node.get("internal_id")

        if node["platform"] == "nebula":
            internalvalue = nebulanodes.get(internalid, None)
            node["internal_info"] = internalvalue
            node["state"] = NUM2VMSTATE.get(nebulanodes.get(internalid, {}).get("STATE"), "UNKNOWN")

        else:
            # OpenStack
            pass

    return nodes_d


def get_nodes_db_for_output(tags=None, nodeids=None):
    nodes_d = get_nodes_db(tags, nodeids)

    nebulanodes = list_nodes_nebula()

    for node in nodes_d.values():
        internalid = node.get("internal_id")

        if node["platform"] == "nebula":
            internalvalue = nebulanodes.get(internalid, {})
            node["state"] = NUM2VMSTATE.get(internalvalue.get("STATE"), "UNKNOWN")
            node["vcpu"] = internalvalue.get("TEMPLATE").get("VCPU")
            node["cpu"] = internalvalue.get("TEMPLATE").get("CPU")

            node["memory"] = internalvalue.get("MEMORY")

            del node["creationtemplate"]

        else:
            # OpenStack
            pass

    return nodes_d


def get_nodes_db(tags=None, nodeids=None):
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        if tags:
            tags = set(tags)
            if not tdata.isadmin:
                tags.add(tdata.ownertag)
            tag_placeholder = ", ".join(["%s" for _ in tags])

            querystart = "SELECT n.* from nodes n, node_taggings nt, tagwords t WHERE t.tag in ("

            queryend = ") AND nt.tag_id = t.id AND n.id = nt.node_id GROUP BY n.id HAVING COUNT( n.id ) = %s ;"

            db_cur.execute(querystart + tag_placeholder + queryend, list(tags) + [len(tags)])
        else:
            if nodeids:
                if not tdata.isadmin:
                    nodeids_placeholder = ", ".join(["%s" for _ in nodeids])

                    querystart = "SELECT n.* from nodes n, node_taggings nt, tagwords t WHERE  n.id in ("

                    queryend = ") AND t.tag=%s AND nt.tag_id = t.id AND n.id = nt.node_id ;"
                    db_cur.execute(querystart + nodeids_placeholder + queryend, nodeids + tdata.ownertag)
                else:
                    nodeids_placeholder = ", ".join(["%s" for _ in nodeids])

                    querystart = "SELECT n.* from nodes n WHERE  n.id in ("

                    queryend = ") ;"
                    db_cur.execute(querystart + nodeids_placeholder + queryend, nodeids)
            else:
                if not tdata.isadmin:
                    query = "SELECT n.* from nodes n, node_taggings nt, tagwords t WHERE t.tag=%s AND nt.tag_id = t.id AND n.id = nt.node_id ;"
                    db_cur.execute(query, (tdata.ownertag,))

                else:
                    db_cur.execute("SELECT * from nodes ;")

        nodes = db_cur.fetchall()

    nodes_d = {}
    for node in nodes:
        nodes_d[node["id"]] = node

    return nodes_d


def get_networks_db(tags=None):
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        if tdata.isadmin and not tags:
            db_cur.execute("SELECT * from networks ;")
        else:
            tags = set(tags)
            if not tdata.isadmin:
                tags.add(tdata.ownertag)

            tag_placeholder = ", ".join(["%s" for _ in tags])

            querystart = "SELECT n.* from networks n, net_taggings nt, tagwords t WHERE t.tag in ("

            queryend = ") AND nt.tag_id = t.id AND n.id = nt.net_id GROUP BY n.id HAVING COUNT( n.id ) = %s ;"

            db_cur.execute(querystart + tag_placeholder + queryend, list(tags) + [len(tags)])

        netsquery = db_cur.fetchall()

    nets_d = {}
    for node in netsquery:
        nets_d[node["id"]] = node

    return nets_d


def get_networks_db_and_internal(tags=None, typeselect=None):
    nets_d = get_networks_db(tags)

    nebulanets_d = list_nebulanets_xml()

    out_d = {}
    for k, v in nets_d.iteritems():
        internalid = v["nebulaid"]
        v["internal_info"] = nebulanets_d.get(internalid, None)

        if typeselect and v["type"] == typeselect:
            out_d[k] = v

    if typeselect:
        return out_d
    return nets_d


def get_networks_db_for_output(tags=None, typeselect=None):
    nets_d = get_networks_db(tags)

    nebulanets_d = list_nebulanets_xml()

    out_d = {}
    for k, v in nets_d.iteritems():
        if typeselect and v["type"] == typeselect:
            out_d[k] = v
        elif typeselect and v["type"] != typeselect:
            continue

        internalid = v["nebulaid"]
        internalinfo = nebulanets_d.get(internalid, {})
        v["used_leases"] = internalinfo.get("USED_LEASES")

    if typeselect:
        return out_d
    return nets_d


def get_used_vxids_db():
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("SELECT vid from networks ;")
        vxids = map(lambda a: a[0], db_cur.fetchall())
    return vxids


def get_node_db(node_id):
    check_user_privilege_node(node_id)

    db_con = tdata.DB_CON

    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        db_cur.execute("SELECT * from nodes WHERE id = %s ;", (node_id,))
        node_d = db_cur.fetchone()

    if not node_d:
        raise NoSuchObjectException("Node with id: %d not found" % (node_id))

    return node_d


def get_node_db_and_internal(nodeid):
    node = get_node_db(nodeid)

    if node["platform"] == "nebula":
        internalid = node["internal_id"]
        try:
            node["internal_info"] = info_node_nebula(internalid)
        except NoSuchObjectException:
            node["internal_info"] = None
            state = "UNKNOWN"
        else:
            state = NUM2VMSTATE.get(node["internal_info"].get("STATE"), "UNKNOWN")
        node["state"] = state
    else:
        # TODO OpenStack
        pass
    return node


def get_node_db_for_output(nodeid):
    node = get_node_db(nodeid)

    if node["platform"] == "nebula":
        internalid = node["internal_id"]
        try:
            internalvalue = info_node_nebula(internalid)
        except NoSuchObjectException:
            internalvalue = {}
            state = "UNKNOWN"
        else:
            state = NUM2VMSTATE.get(internalvalue.get("STATE"), "UNKNOWN")
        node["state"] = state

        node["vcpu"] = internalvalue.get("TEMPLATE").get("VCPU")
        node["cpu"] = internalvalue.get("TEMPLATE").get("CPU")
        node["memory"] = internalvalue.get("MEMORY")
    else:
        # TODO OpenStack
        pass
    return node


def get_templates_db(user=None, extractdefaults=True):
    userid = tdata.userid
    if user:
        if tdata.username != user and not tdata.isadmin:
            raise PrivilegeException("you can only access own or public templates")

        userinfo = get_user(user)
        if not userinfo:
            raise NoSuchObjectException("user: {0} doesn't exist".format(user))
        userid = userinfo["id"]
        debug_log_print(userid)

    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        if not user:
            if tdata.isadmin:
                db_cur.execute("SELECT * from templates;")
            else:
                db_cur.execute("SELECT * from templates userid=%s OR user=NULL ;", (userid,))
        else:
            db_cur.execute("SELECT * from templates WHERE userid=%s ;", (userid,))
        templ_ds = db_cur.fetchall()

    templates = {}
    for templ in templ_ds:
        if extractdefaults:
            templ["defaultvalues"] = json.loads(templ["defaultvalues"])

        templates[templ["id"]] = templ

    return templates


def get_interfaces_db(netid=None, nodeid=None):
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        if not netid and not nodeid:
            db_cur.execute("SELECT * from interfaces;")
        elif netid and nodeid:
            db_cur.execute("SELECT * from interfaces WHERE net_id=%s AND node_id=%s ;", (netid, nodeid))
        elif netid:
            db_cur.execute("SELECT * from interfaces WHERE net_id=%s ;", (netid,))
        else:
            db_cur.execute("SELECT * from interfaces WHERE node_id=%s ;", (nodeid,))

        results = db_cur.fetchall()
    intfs_d = {}
    for i in results:
        intfs_d[i["id"]] = i

    return intfs_d


def get_interface_db(intfid):
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        db_cur.execute("SELECT * from interfaces WHERE id=%s ;", (intfid,))
        res_d = db_cur.fetchone()
    if not res_d:
        raise NoSuchObjectException("no interface with such id")
    return res_d


def get_nodetemplate_db(templid=None, templname=None, extractdefaults=True):
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        if templid:
            db_cur.execute("SELECT * from templates WHERE id = %s ;", (templid,))
            templ_d = db_cur.fetchone()
        elif templname:
            db_cur.execute("SELECT * from templates WHERE name = %s ;", (templname,))
            templ_d = db_cur.fetchone()
        else:
            templ_d = None

    if not tdata.isadmin and templ_d["userid"] and templ_d["userid"] != tdata.userid:
        raise PrivilegeException("this template id is privately owned by other player")

    if not templ_d:
        raise NoSuchObjectException("Template not found")

    if extractdefaults:
        templ_d["defaultvalues"] = json.loads(templ_d["defaultvalues"])

    return templ_d


def add_node_db(node_d):
    nodeid = None
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        node_tuple = (
            node_d.get("name", None), node_d.get("internal_id", None), datetime.utcnow(),
            node_d["platform"], node_d.get("creationtemplate"))
        db_cur.execute(
                "INSERT into nodes (name, internal_id, lastchange, platform, creationtemplate) VALUES ( %s, %s, %s, %s, %s) RETURNING id;",
                node_tuple)
        try:
            nodeid = db_cur.fetchone()[0]
        except psycopg2.IntegrityError:
            debug_log("Such node name (%s) already exists in DB." % (node_d["name"],))
            raise DuplicateNameException("Such node name (%s) already exists in DB." % (node_d["name"],))

    return nodeid


def add_interface_db(info_d, netid):
    # info_d  je node_d ale s pridanymi parametry
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        intf_tuple = (info_d["id"], info_d.get("mac_addr"), info_d.get("ip", None), netid, info_d.get("shaping", ""))
        isok = True
        try:
            db_cur.execute(
                    "INSERT into interfaces (node_id, mac_addr, ip_addr, net_id, shaping) VALUES (%s, %s, %s, %s, %s) RETURNING id;",
                    intf_tuple)
            dbid = db_cur.fetchone()[0]
        except psycopg2.IntegrityError as e:
            debug_log("nebula_attach_node_to_net - INSERT" + str(intf_tuple))
            raise GeneralAPIError(e + str(intf_tuple))
    return dbid

def update_interface_db(intfid, intf_d):
# TODO TEST
    original_d = get_interface_db(intfid)

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:

        intf_props = [intf_d.get("node_id", original_d["node_id"]), intf_d.get("mac_addr", original_d["mac_addr"]),
                      intf_d.get("ip_addr", original_d["ip_addr"]), intf_d.get("net_id", original_d["net_id"]),
                      intf_d.get("shaping", original_d["shaping"])]

        db_cur.execute("UPDATE interfaces SET node_id=%s, mac_addr=%s, ip_addr=%s, net_id=%s, shaping=%s  WHERE id=%s ;",
                       intf_props + [intfid])



def delete_node_db(nodeid):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("DELETE from nodes WHERE id = %s ;", (nodeid,))


def delete_net_db(netid):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("DELETE from networks WHERE id = %s ;", (netid,))


def update_node_db(node_id, node_d):
    # check_user_privilege_node(node_id)

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        node_props = [node_d["name"], node_d["internal_id"], datetime.utcnow(), node_d["platform"]]

        db_cur.execute("UPDATE nodes SET name=%s, internal_id=%s, lastchange=%s, platform=%s WHERE id=%s ;",
                       node_props + [node_id])


def increase_net_size_db(netid, howmuch=1):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("UPDATE networks SET size=size+%s WHERE id=%s ;", (howmuch, netid))


def decrease_net_size_db(netid, howmuch=1):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("UPDATE networks SET size=size-%s WHERE id=%s ;", (howmuch, netid))


def add_network_db(net_d, type="pt2pt", size=2):
    db_con = tdata.DB_CON
    net_tuple = [net_d["nebulaid"], size, net_d["vxid"], type, datetime.utcnow()]

    with db_con.cursor() as db_cur:
        # if startmac:
        #     debug_log_print(startmac, startmac.nummeric, str(startmac))
        #     debug_log_print(net_tuple+[startmac])
        db_cur.execute(
                "INSERT into networks (nebulaid,size,vid,type,reservedsince) VALUES (%s, %s, %s, %s, %s) RETURNING id;",
                net_tuple)
        # else:
        #     db_cur.execute("INSERT into networks (nebulaid,size,used,vid,type,shaping,reservedsince) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;" ,net_tuple)
        netid = db_cur.fetchone()[0]

    add_tag_network(tdata.ownertag, netid)

    return netid


def add_nodetemplate_db(templstring, name, defaultvalues=None, defaultuse=False, userid=None, user=None,
                        platform="nebula"):
    if user and isinstance(user, basestring):
        userid = get_user(username=user)["id"]

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        try:
            db_cur.execute(
                    "INSERT into templates (name,template,defaultvalues,defaultuse,userid,platform) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;",
                    (name, templstring, defaultvalues, defaultuse, userid, platform))
            dbid = db_cur.fetchone()[0]
        except psycopg2.IntegrityError  as e:
            add_to_user_problem_msg("template with name {0:s} already exists".format(name))
            raise DuplicateNameException("template with name {0:s} already exists".format(name))
    return dbid


def create_tag(tagname):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        try:
            db_cur.execute("INSERT into tagwords (tag) VALUES (%s) ;", (tagname,))
        except psycopg2.IntegrityError:
            # add_to_user_problem_msg("tag with name {0:s} already exists".format(tagname))
            raise DuplicateNameException("tag with name {0} already exists".format(tagname))


def add_tag_node(tags, node):
    if isinstance(tags, basestring):
        tags = [tags]

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        for tag in tags:
            try:
                db_cur.execute(
                        "INSERT into node_taggings (node_id, tag_id) VALUES (%s, (SELECT id from tagwords WHERE tag =%s)) ;",
                        (node, tag))
            except psycopg2.IntegrityError as e:
                if "violates foreign key constraint" in e:
                    add_to_user_problem_msg("such node id doesn't exist")
                    raise NoSuchObjectException("such node id doesn't exist")
                elif 'null value in column "tag_id" violates not-null constraint' in e:
                    add_to_user_problem_msg("such tag doesn't exist")
                    raise NoSuchObjectException("such tag doesn't exist")
                elif 'violates unique constraint "node_taggings_pkey"':
                    add_to_user_problem_msg("tag {0} already added".format(tag))
                else:
                    raise






def remove_tag_node(tags, node):
    if isinstance(tags, basestring):
        tags = [tags]

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        for tag in tags:
            try:
                db_cur.execute(
                        "DELETE from node_taggings where node_id=%s and tag_id=(SELECT id from tagwords WHERE tag=%s);",
                        (node, tag))
            except psycopg2.IntegrityError as e:
                if "violates foreign key constraint" in e:
                    add_to_user_problem_msg("such node id doesn't exist")
                    raise NoSuchObjectException("such node id doesn't exist")
                elif 'null value in column "tag_id" violates not-null constraint' in e:
                    add_to_user_problem_msg("such tag doesn't exist")
                    raise NoSuchObjectException("such tag doesn't exist")
                raise


def add_tag_network(tags, net):
    if isinstance(tags, basestring):
        tags = [tags]

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        for tag in tags:
            try:
                db_cur.execute(
                        "INSERT into net_taggings (net_id, tag_id) VALUES (%s, (SELECT id FROM tagwords WHERE tag=%s)) ;",
                        (net, tag))
            except psycopg2.IntegrityError as e:
                if "violates foreign key constraint" in e:
                    debug_log_print("such net id doesn't exist")
                    raise NoSuchObjectException("such net id doesn't exist")

                elif 'null value in column "tag_id" violates not-null constraint' in e:
                    debug_log_print("such tag doesn't exist")
                    raise DuplicateNameException("such tag doesn't exist")
                else:
                    debug_log_print("add net integrity error: %s" % (e,))
                    raise GeneralAPIError("add net integrity error: %s" % (e,))


def add_user(username, password, isadmin=False, nebulauser=None):
    if not isadmin and not tdata.isadmin:
        add_to_user_problem_msg("only admin user can add users")
        raise PrivilegeException("only admin user can add users")


    saltstr = "".join(random.choice(SALTCHARS) for _ in range(SALTLEN))
    # derivedkey = hashlib.pbkdf2_hmac('sha256', password, saltstr, 100000)
    # hexalified = binascii.hexlify(derivedkey)

    hexalified = hashlib.sha512(password + saltstr).hexdigest()

    inserttuple = (username, hexalified, saltstr, isadmin, nebulauser)

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        try:
            db_cur.execute(
                "INSERT into users (name, password, salt, isadmin, nebulauser) VALUES (%s, %s, %s, %s, %s) ;",
                inserttuple)
        except psycopg2.IntegrityError as e:
            debug_log_print_ext("user couldn't be added, probably duplicate;\n %s" % (e,))
            raise GeneralAPIError("user couldn't be added, probably duplicate")

    create_tag("owner:{0}".format(username))
    return True


def get_user(username, verifybypass=False):
    if not verifybypass and username != tdata.username and tdata.isadmin == False:
        add_to_user_problem_msg("only admin user or user himself can do this")
        raise PrivilegeException("access denied")

    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        db_cur.execute("SELECT * FROM users WHERE name=%s ;", [username])
        res_d = db_cur.fetchone()

    if not res_d:
        add_to_user_problem_msg("user '{0}' not in database".format(username))
        raise NoSuchObjectException("user of such name doesn't exist")

    return res_d


#TODO TEST
def get_users():
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        db_cur.execute("SELECT id, name, isadmin, nebulauser FROM users ;")
        results = db_cur.fetchall()

    res_d = {}
    for user in results:
        res_d[user["name"]] = user

    return res_d

#TODO TEST
def change_user(username, user_d):
    if username != tdata.username and tdata.isadmin == False:
        add_to_user_problem_msg("only admin user or user himself can do this")
        raise PrivilegeException("access denied")

    if user_d["isadmin"] and not tdata.isadmin:
        add_to_user_problem_msg("only admin can add user privileges")
        raise PrivilegeException("access denied")

    original_d = get_user(username)

    new_d = {}
    for k in original_d.keys():
        new_d[k] = user_d.get(k, original_d[k])

    if "password" in user_d:
        hexalified = hashlib.sha512(user_d["password"] + new_d["salt"]).hexdigest()
        new_d["password"] = hexalified

    updatetuple = [new_d["password"], new_d["salt"], new_d["isadmin"],new_d["nebulauser"],username]
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        db_cur.execute("UPDATE users SET password=%s, salt=%s, isadmin=%s, nebulauser=%s WHERE name=%s ;", updatetuple)

    changed = get_user(username)
    return changed


def get_tags():
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("SELECT tag FROM tagwords ;")
        tags = db_cur.fetchall()
    tags = map(lambda a: a[0], tags)
    return tags


def get_tags_node(nodeid):
    """

    :param nodeid:
    :type nodeid:
    :return:
    :rtype: list
    """
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("SELECT tag FROM node_taggings, tagwords WHERE node_id=%s and tag_id=id ;", (nodeid,))
        tags = db_cur.fetchall()
    if not tags:
        raise NoSuchObjectException("such node id doesn't exist")
    tags = map(lambda a: a[0], tags)
    return tags


def get_tags_net(netid):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("SELECT tag FROM net_taggings, tagwords WHERE net_id=%s and tag_id=id ;", (netid,))
        tags = db_cur.fetchall()
    tags = map(lambda a: a[0], tags)
    return tags


def add_new_networks_db():
    def get_networks_db():
        db_con = tdata.DB_CON

        with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
            db_cur.execute("SELECT * from networks;")
            net_ds = db_cur.fetchall()

        nets = {}
        for nd in net_ds:
            nets[nd["nebulaid"]] = nd

        return nets

    dbnets = get_networks_db()

    debug_print("puvodni site")
    debug_print(dbnets)
    nebulanets = list_nebulanets_xml()
    debug_print("nebula site")
    debug_print(nebulanets)

    for k in nebulanets.keys():
        if k not in dbnets:
            n = nebulanets[k]
            n["id"] = n["ID"]
            if "VLAN" in n and n["VLAN"] == "1":
                n["vxid"] = n["VLAN_ID"]
            else:
                n["vxid"] = None
            netsize = 0
            if "AR_POOL" in n:
                for v in n["AR_POOL"].itervalues():
                    netsize += v["SIZE"]

            add_network_db(n, size=netsize)
            debug_print(k)


def delete_nebulainterface_db(intfid):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("DELETE FROM interfaces WHERE id=%s ;", (intfid,))
    return True


def remove_disconnect_interface(intfid, deleteaddrarr=False):
    intf_d = get_interface_db(intfid)

    net_d = get_network_db(intf_d["net_id"])

    node_d = get_node_db(intf_d["node_id"])

    check_state_nebula(node_d["internal_id"], lcmstate="RUNNING", tries=1)

    nebulanode = info_node_nebula(node_d["internal_id"])
    nics = nebulanode["TEMPLATE"]["NIC"]
    found = False
    for nic_d in nics:
        if nic_d['NETWORK_ID'] == net_d["nebulaid"] and nic_d['MAC'] == intf_d["mac_addr"]:
            nic_id = nic_d['NIC_ID']
            found = True
            break

    if not found:
        debug_log_print_ext("inside nebula is no maching interface", nics)
        raise GeneralAPIError("error detaching net interface, inside nebula is no maching interface")

    out, stderr = run_cmd("onevm  nic-detach  {0} {1}".format(node_d["internal_id"], nic_id))
    if out:
        debug_log_print_ext("dettaching nic in nebula unsuccessful",
                            "onevm  nic-detach  {0} {1}".format(node_d["internal_id"], net_d["nebulaid"]), out)
        raise GeneralAPIError("dettaching nic in nebula unsuccessful")

    if net_d["type"] == "pt2pt" and deleteaddrarr:
        try:
            remove_addrarr_nebulanet(intf_d["net_id"], intf_d["mac_addr"])
        except Exception as e:
            # neni vazne , vzhledem k tomu, ze nic-detach nijak nervalo
            debug_log_print_ext("error removeing addrarr from nebulanet", repr(e))

    delete_nebulainterface_db(intfid)
    return True


def remove_network(netid):
    # also privilege check
    net_d = get_network_db(netid)

    attached_interfaces = get_interfaces_db(netid)

    node_ids = map(lambda a: a["node_id"], attached_interfaces.itervalues())

    node_nebulaids = map(lambda a: a["internal_id"], get_nodes_db(nodeids=node_ids).itervalues())

    for nebulaid in node_nebulaids:
        check_state_nebula(nebulaid, lcmstate="RUNNING", tries=1)

    results = []
    for intf in attached_interfaces.itervalues():
        try:
            result = remove_disconnect_interface(intf["id"])
        except Exception as e:
            debug_log_print_ext(repr(e))
            result = False
        finally:
            results.append(result)

    if all(results):  # everything successful
        delete_net_db(netid)
    else:
        raise GeneralAPIError("removing network {0} wasn't successful,\
         some attached interfaces couldn't be disconnected".format(netid))

    out, stderr = run_cmd("onevnet delete {0}".format(net_d["nebulaid"]))
    if out:
        debug_log_print("network wasn't deleted from nebula", "orphan nebula net {0}".format(net_d["nebulaid"]))

    return True


def create_vxlan_nebulanet_ether(mac, size, addars=None, nettype="pt2pt"):
    temp_net_f = tempfile.NamedTemporaryFile(delete=False)

    with open(TEMPLATE_PATH + LINK_TEMPLATE_FILE, "r") as nt:
        nettemplate = string.Template(nt.read())

    used_vlanids = nebulaid_to_vxlanid_mapping().values()

    vxid = 0
    while True:
        # TODO potentially infinite loop, all may be used up
        vxid = random.randint(VXIDSTART, VXIDEND)
        if vxid not in used_vlanids:
            break

    combinedsize = size

    subst_dict = {"vlanid": vxid}
    netstr = nettemplate.safe_substitute(subst_dict)
    netstr += ADDRESS_RANGE_ETHER.format(mac, size) + "\n"

    if addars:
        for mac, size in addars:
            netstr += ADDRESS_RANGE_ETHER.format(mac, size) + "\n"
            combinedsize += size

    temp_net_f.write(netstr)
    temp_net_f.flush()
    temp_net_f.close()
    tname = temp_net_f.name

    debug_log_print("onevnet -c %s create %s" % (CLUSTER_NAME, tname))
    out, stderr = run_cmd("onevnet create -c {0}  {1}".format(CLUSTER_NAME, tname))

    if "ID:" == out[:3]:
        os.remove(tname)
    else:
        debug_log_print_ext(out)
        raise GeneralAPIError(out)

    nebulanetid = int(out.split()[1])

    net_d = {"nebulaid": nebulanetid, "vxid": vxid}

    netid = add_network_db(net_d, nettype, size=combinedsize)

    debug_log_print("Nebula net %d added as network with db id %d " % (nebulanetid, netid))

    return netid


def create_link(mac1, mac2=None):
    temp_net_f = tempfile.NamedTemporaryFile(delete=False)

    with open(TEMPLATE_PATH + LINK_TEMPLATE_FILE, "r") as nt:
        nettemplate = string.Template(nt.read())

    # used_vlanids = map(lambda a: a.get('bridge').replace("onebr0-vlan",""),list_nebulanets())
    used_vlanids = nebulaid_to_vxlanid_mapping().values()

    vxid = 0
    while True:
        # TODO potentially infinite loop, all may be used
        vxid = random.randint(VXIDSTART, VXIDEND)
        if vxid not in used_vlanids:
            break

    subst_dict = {"vlanid": vxid}

    netstr = nettemplate.safe_substitute(subst_dict)

    netstr += ADDRESS_RANGE_ETHER.format(mac1, 1) + "\n"
    if mac2:
        netstr += ADDRESS_RANGE_ETHER.format(mac2, 2) + "\n"

    temp_net_f.write(netstr)
    temp_net_f.flush()
    temp_net_f.close()
    tname = temp_net_f.name

    debug_log_print("onevnet -c %s create %s" % (CLUSTER_NAME, tname))
    out, stderr = run_cmd("onevnet create -c {0}  {1}".format(CLUSTER_NAME, tname))

    if "ID:" == out[:3]:
        os.remove(tname)
    else:
        debug_log(out)
        raise GeneralAPIError(out)

    nebulanetid = int(out.split()[1])

    net_d = {"nebulaid": nebulanetid, "vxid": vxid}

    netsize = 1
    if mac2:
        netsize = 2

    netid = add_network_db(net_d, "pt2pt", size=netsize)

    debug_log_print('Nebula net {0} added as network with db id {1} '.format(nebulanetid, netid))
    time.sleep(3)
    return netid


def create_flat_nebulanet(size=253, startmac=None, startip=None, vxlan=False, netaddr=None, netmask=None, gateway=None):
    subst_dict = {}

    vxid = None
    if vxlan:
        type = "vxlan-flat"

        used_vlanids = nebulaid_to_vxlanid_mapping().values()

        while True:
            # TODO potentially infinite loop, all may be used
            vxid = random.randint(VXIDSTART, VXIDEND)
            if vxid not in used_vlanids:
                break
        subst_dict["vlanid"] = vxid
        with open(TEMPLATE_PATH + VXLAN_FLAT_TEMPLATE_FILE, "r") as nt:
            nettemplate = string.Template(nt.read())
    else:
        type = "plain-flat"
        with open(TEMPLATE_PATH + PLAIN_FLAT_TEMPLATE_FILE, "r") as nt:
            nettemplate = string.Template(nt.read())

    # get name:
    usednames = map(lambda a: a["NAME"], list_nebulanets_xml().itervalues())
    while True:
        namenum = random.randint(0, 1000)
        netname = FLAT_NET_NAME_TEMPL.format(namenum)
        if netname not in usednames:
            subst_dict["lanname"] = netname
            break

    netstr = nettemplate.safe_substitute(subst_dict)

    if startip and startmac:
        netstr += ADDRESS_RANGE_IP4_ETHER.format(startip, startmac, size) + "\n"
    elif startip:
        netstr += ADDRESS_RANGE_IP4.format(startip, size)
    else:
        if not startmac:
            startmac = MacAddress.from_parts(macprefix=FLAT_MAC_PREFIX, macsuffix="01")
        netstr += ADDRESS_RANGE_ETHER.format(startmac, size)

    if startip:
        if netaddr:
            netstr += 'NETWORK_ADDRESS = "{0}"\n'.format(netaddr)
        if netmask:
            netstr += 'NETWORK_MASK = "{0}"\n'.format(netmask)
        if gateway:
            netstr += 'GATEWAY = "{0}"\n'.format(gateway)

    temp_net_f = tempfile.NamedTemporaryFile(delete=False)
    temp_net_f.write(netstr)
    temp_net_f.flush()
    temp_net_f.close()
    tname = temp_net_f.name

    debug_log_print("onevnet -c %s create %s" % (CLUSTER_NAME, tname))
    out, stderr = run_cmd("onevnet create -c {0}  {1}".format(CLUSTER_NAME, tname))

    if "ID:" == out[:3]:
        os.remove(tname)
    else:
        debug_log_print_ext("ERROR onevnet creation:", tname, out)
        raise GeneralAPIError(out)

    nebulanetid = int(out.split()[1])

    net_d = {"nebulaid": nebulanetid, "vxid": vxid}

    netid = add_network_db(net_d, type, size=size)

    return netid


def attach_node_to_net(node_d, netid):
    if node_d["platform"] == "nebula":
        result = nebula_attach_node_to_net(node_d, netid)
    else:
        ## TODO openstack
        result = None
    return result


# TODO FIX!
def nebula_attach_node_to_net(node_d, netid):
    net_d = get_network_db(netid)
    if not net_d["nebulaid"]:
        raise GeneralAPIError("network wasn't properly initialized")
    nebulanetid = net_d["nebulaid"]

    # TODO - vyradit? used z db porusuje to x tou normu, muzu ziskat z interfaces - proc ne?
    if net_d["size"] <= int(info_nebulanet(nebulanetid)["USED_LEASES"]):
        raise GeneralAPIError("network size is not enough")

    intid = node_d["internal_id"]
    out, stderr = run_cmd("onevm nic-attach {0}  --network {1}".format(intid, nebulanetid))
    debug_log_print("onevm nic-attach {0}  --network {1}".format(intid, nebulanetid))

    if out:  # pri uspechu se nepise nic, jinak ano
        debug_log(out)
        raise GeneralAPIError(out)
    # increase_net_use_db(netid,howmuch=1)

    change_condition = threading.Condition()
    with change_condition:
        cb = NotifyTask(node_ids=[node_d["id"]], change_selector=None, towhat=None, howmany=1,
                        notifycondition=change_condition)
        while True:
            callbacks_in_queue.put(cb)
            change_condition.wait()
            nebulanode = info_node_nebula(intid)
            debug_print(nebulanode["TEMPLATE"]["NIC"])
            attached_netids = map(lambda a: a["NETWORK_ID"], nebulanode["TEMPLATE"]["NIC"])
            if nebulanetid in attached_netids:
                break

    ind = attached_netids.index(nebulanetid)
    node_d["mac_addr"] = nebulanode["TEMPLATE"]["NIC"][ind]["MAC"]

    dbid = add_interface_db(node_d, netid)

    return dbid


# TODO implement maxtime check
def change_node_state(nodeid, whattodo, waitforit=True):
    OPTIONS = ["hold", "shutdown", "stop", "resume"]
    VM_STATE = ["INIT", "PENDING", "HOLD", "ACTIVE", "STOPPED", "SUSPENDED", "DONE", "FAILED", "POWEROFF", "UNDEPLOYED"]

    state_action = {("POWEROFF", "LCM_INIT"): ["resume"],
                    ("ACTIVE", "RUNNING"): ["stop", "suspend", "poweroff", "undeploy", "reboot"],
                    ("STOPPED", "LCM_INIT"): ["resume"],
                    ("UNDEPLOYED", "LCM_INIT"): ["resume"],
                    ("SUSPENDED", "LCM_INIT"): ["resume"]}

    wanted_lcmstate_after_action = {"resume": "RUNNING",
                                    "stop": "LCM_INIT",
                                    "suspend": "LCM_INIT",
                                    "poweroff": "LCM_INIT",
                                    "undeploy": "LCM_INIT",
                                    "reboot": "RUNNING"}
    wanted_vmstate_after_action = {"resume": "ACTIVE",
                                   "stop": "STOPPED",
                                   "suspend": "SUSPENDED",
                                   "poweroff": "POWEROFF",
                                   "undeploy": "UNDEPLOYED",
                                   "reboot": "ACTIVE"}

    node_d = get_node_db(nodeid)

    if node_d["platform"] == "nebula":

        states_d = get_node_state_nebula(node_d["internal_id"])

        statetuple = (states_d["vm_state"], states_d["lcm_state"])

        if statetuple in state_action:
            if whattodo in state_action[statetuple]:
                out, stderr = run_cmd("onevm %s %s" % (node_d["internal_id"], whattodo))
                if out:
                    debug_log_print("error changing state", "onevm %s %s" % (node_d["internal_id"], whattodo), out)
                    raise GeneralAPIError("error changing state" + out)

                if waitforit:
                    change_condition = threading.Condition()
                    with change_condition:
                        cb = NotifyTask(node_ids=[nodeid], change_selector="LCM_STATE",
                                        towhat=LCMSTATE2NUM[wanted_lcmstate_after_action[whattodo]], howmany=1,
                                        notifycondition=change_condition)
                        callbacks_in_queue.put(cb)
                        while True:
                            if get_node_state_nebula(node_d["internal_id"])["LCM_STATE"] == \
                                    wanted_lcmstate_after_action[whattodo]:
                                break
                            else:
                                change_condition.wait()

            else:
                debug_log_print("command %s not possible in vm state: %s , lcm state %s" % (
                    whattodo, states_d["vm_state"], states_d["lcm_state"]))
                raise GeneralAPIError("command %s not possible in vm state: %s , lcm state %s" % (
                    whattodo, states_d["vm_state"], states_d["lcm_state"]))
        else:
            debug_log_print("in vm state: %s , lcm state %s is not possible to change state" % (
                states_d["vm_state"], states_d["lcm_state"]))
            raise GeneralAPIError("in vm state: %s , lcm state %s is not possible to change state" % (
                states_d["vm_state"], states_d["lcm_state"]))


    else:  # OpenStack
        pass

    return True


# TODO implement maxtime check
def change_node_state_cruder(nodeid, desiredstate, waitforit=True):
    OPTIONS = ["hold", "shutdown", "stop", "resume"]
    VM_STATE = ["INIT", "PENDING", "HOLD", "ACTIVE", "STOPPED", "SUSPENDED", "DONE", "FAILED", "POWEROFF", "UNDEPLOYED"]

    state_action = {("POWEROFF", "LCM_INIT"): ["resume"],
                    ("ACTIVE", "RUNNING"): ["stop", "suspend", "poweroff", "undeploy", "reboot"],
                    ("STOPPED", "LCM_INIT"): ["resume"],
                    ("UNDEPLOYED", "LCM_INIT"): ["resume"],
                    ("SUSPENDED", "LCM_INIT"): ["resume"]}

    wanted_vmstate_after_action = {"resume": "ACTIVE",
                                   "stop": "STOPPED",
                                   "suspend": "SUSPENDED",
                                   "poweroff": "POWEROFF",
                                   "undeploy": "UNDEPLOYED",
                                   "reboot": "ACTIVE"}
    neededstate2action = {v: k for k, v in wanted_vmstate_after_action.iteritems()}

    if desiredstate not in neededstate2action:
        raise WrongRequestException(
                "there is no such state possible, choose one of {0}".format(neededstate2action.keys()))

    node_d = get_node_db(nodeid)

    if node_d["platform"] == "nebula":

        states_d = get_node_state_nebula(node_d["internal_id"])

        statetuple = (states_d["vm_state"], states_d["lcm_state"])

        if statetuple in state_action:
            whattodo = neededstate2action.get(desiredstate)
            if neededstate2action.get(desiredstate) in state_action[statetuple]:
                out, stderr = run_cmd("onevm %s %s" % (node_d["internal_id"], whattodo))
                if out:
                    debug_log_print("error changing state", "onevm %s %s" % (node_d["internal_id"], whattodo), out)
                    raise GeneralAPIError("error changing state" + out)

                if waitforit:
                    change_condition = threading.Condition()
                    with change_condition:
                        cb = NotifyTask(node_ids=[nodeid], change_selector="STATE",
                                        towhat=VMSTATE2NUM[desiredstate], howmany=1,
                                        notifycondition=change_condition)
                        callbacks_in_queue.put(cb)
                        while True:
                            if get_node_state_nebula(node_d["internal_id"])["STATE"] == desiredstate:
                                break
                            else:
                                change_condition.wait()

            else:
                # debug_log_print("change to state {0} not possible from state {1}, lcm_state: \
                # {2}".format(desiredstate, states_d["vm_state"],states_d["lcm_state"]))
                raise GeneralAPIError("change to state {0} not possible from state {1}, lcm_state: \
                 {2}".format(desiredstate, states_d["vm_state"], states_d["lcm_state"]))
        else:
            add_to_user_problem_msg(
                    "in vm state: {0:s} , lcm state {1:s} is not possible to change state".format(states_d["vm_state"],
                                                                                                  states_d[
                                                                                                      "lcm_state"]))
            raise WrongStateForActionException(
                    "in vm state: {0:s} , lcm state {1:s} is not possible to change state".format(states_d["vm_state"],
                                                                                                  states_d[
                                                                                                      "lcm_state"]))

    else:  # OpenStack
        pass

    return True


def connect_nodes_nebula(n1, n2, mac1=None, mac2=None):
    if not mac1:
        mac1 = str(MacAddress.from_parts(macprefix=MAC_PREFIX_DEFAULT))
    if not mac2:
        mac2 = str(MacAddress.from_parts(macprefix=MAC_PREFIX_DEFAULT))

    node1_d = get_node_db(n1)
    # node1_d["mac_addr"] = mac1
    node2_d = get_node_db(n2)

    check_state_nebula(node1_d["internal_id"], lcmstate="RUNNING", tries=1)
    check_state_nebula(node2_d["internal_id"], lcmstate="RUNNING", tries=1)

    netid = create_link(mac1=mac1)

    net_d = get_network_db(netid)
    try:
        intfid1 = attach_node_to_net(node1_d, netid)
    except BaseException as e:
        debug_log_print_ext("attach node to net error", e),
        delete_net_db(netid)
        run_cmd("onevnet delete {0}".format(net_d["nebulaid"]))
        raise

    net_d = get_network_db(netid)
    add_addrarr_nebulanet(netid, mac2, 1)

    node2_d = get_node_db(n2)
    # node2_d["mac_addr"] = mac2

    try:
        intfid2 = attach_node_to_net(node2_d, netid)
    except BaseException as e:
        debug_log_print_ext(e)
        try:
            remove_disconnect_interface(intfid1, deleteaddrarr=False)
        except:
            pass
        try:
            delete_net_db(netid)
        except:
            pass
        run_cmd("onevnet delete {0}".format(net_d["nebulaid"]))
        raise

    return {"id": netid, "interface_id1": intfid1, "interface_id2": intfid2}


def create_node(templatename, **kwargs):
    templ_d = get_nodetemplate_db(templname=templatename)
    if templ_d["platform"] == "nebula":
        return create_node_nebula(templ_d["id"], **kwargs)
    else:
        # TODO OpenStack
        pass


def create_node_nebula(templateid, nics=None, tags=None, **kwargs):
    # TODO nics

    ownertag = tdata.ownertag
    if not tags:
        tags = [ownertag]
    if tags is not None and isinstance(tags, basestring):
        tags = set(tags.split(","))
        tags.add(ownertag)

    templ_d = get_nodetemplate_db(templateid)

    vmtempl = string.Template(templ_d["template"])

    for k, v in kwargs.iteritems():
        templ_d["defaultvalues"][k] = v

    node_d = {"name": kwargs.get("name", None),
              "platform": "nebula"}

    # add to db
    db_id = add_node_db(node_d)

    # add tags
    for tag in tags:
        try:
            create_tag(tag)
        except:
            pass
        add_tag_node(tag, db_id)

    temp_templ_f = tempfile.NamedTemporaryFile(delete=False)
    temp_templ_f.write(vmtempl.safe_substitute(templ_d["defaultvalues"]))
    # debug_log_print(vmtempl.safe_substitute(templ_d["defaultvalues"]))
    temp_templ_f.flush()
    temp_templ_f.close()
    tname = temp_templ_f.name

    out, stderr = run_cmd("onevm create %s" % (tname))

    if "ID:" != out[:3]:
        delete_node_db(db_id)
        debug_log_print_ext("failed node creation", vmtempl.safe_substitute(templ_d["defaultvalues"]),
                            "onevm create %s" % (tname), out, )
        raise GeneralAPIError("Error creating vm")
    # template was ok, delete
    os.unlink(tname)

    internalid = int(out.split()[1])

    ## TODO nasledujici predelat na samostatnou funkci, kvuli pouziti s callbacky
    change_condition = threading.Condition()
    with change_condition:
        inittime = datetime.utcnow()
        cb = NotifyTask(node_ids=[db_id], change_selector=None, towhat=None, howmany=1,
                        notifycondition=change_condition)
        nebulainfo = None
        # pokud se de 15 vterin neobjevi v nebule , tak je to fail
        while totimestamp(inittime) + 15 >= totimestamp(datetime.utcnow()):
            try:
                nebulainfo = info_node_nebula(internalid)
                if nebulainfo:
                    break
            except NoSuchObjectException:
                callbacks_in_queue.put(cb)
                change_condition.wait()
    # opennebula porad nezacala schedulovat
    if not nebulainfo:
        delete_node_db(db_id)
        debug_log_print_ext("too long wait for scheduling")
        raise GeneralAPIError("too long wait for scheduling")

    time.sleep(4.5)
    nebulainfo = info_node_nebula(internalid)
    usertemplate = nebulainfo["USER_TEMPLATE"]
    sched_msg = usertemplate.get("SCHED_MESSAGE", "")
    if "No host with enough capacity to deploy the VM" in sched_msg:
        debug_log_print_ext("No host with enough capacity to deploy the VM")
        out, stderr = run_cmd("onevm delete {0}".format(internalid))
        delete_node_db(db_id)
        raise GeneralAPIError("too long wait for scheduling; {0}".format(out))

    node_d["name"] = nebulainfo["NAME"]
    node_d["internal_id"] = internalid

    update_node_db(db_id, node_d)

    debug_log_print("Node created:", get_node_db_and_internal(db_id))

    return db_id


def delete_node(dbid):
    node_d = get_node_db(dbid)

    if node_d["platform"] == "nebula":
        deleted = False
        internalid = node_d["internal_id"]

        nodeinterfaces = get_interfaces_db(netid=None, nodeid=dbid)

        if internalid:  # node mozna nikdy nebyla vyvorena (i kdyz to by se nemelo stat)
            out, stderr = run_cmd("onevm delete {0}".format(internalid))
            # if out and not "[VirtualMachineAction] Error getting virtual machine" in out:
            #     raise GeneralAPIError(out)

        delete_node_db(dbid)

    else:
        pass
    return True


def add_addrarr_nebulanet(netid, mac, size):
    net_d = get_network_db(netid)

    internalid = net_d["nebulaid"]

    out, stderr = run_cmd("onevnet addar {0} --mac {1} --size {2}".format(internalid, mac, size))

    if out:
        debug_log_print_ext("address range wasn't added to net {0}: ".format(internalid), out)
        GeneralAPIError("address range wasn't added to net")
    increase_net_size_db(netid, howmuch=size)


def remove_addrarr_nebulanet(netid, startmac):
    net_d = get_network_db_and_internal(netid)

    arpool = net_d.get("internal_info", {}).get("AR_POOL")
    if not arpool:
        debug_log_print_ext(
                "underlying nebulanetwork isn't available or has no Address Ranges; netid: {0}, startmac: {1}".format(
                    netid,
                    startmac))
        raise NoSuchObjectException(
                "underlying nebulanetwork isn't available or has no Address Ranges; netid: {0}, startmac: {1}".format(
                    netid,
                    startmac))

    for addrrange in arpool:
        ar_id = addrrange["AR_ID"]
        mac = addrrange["MAC"]
        size = addrrange["SIZE"]

        if mac == startmac:
            break
    if mac != startmac:
        debug_log_print_ext("there is no Address Range in netid: {0} with startmac: {1}".format(netid, startmac))
        raise NoSuchObjectException(
                "there is no Address Range in netid: {0} with startmac: {1}".format(netid, startmac))

    for i in range(4):
        out, stderr = run_cmd("onevnet rmar {0} {1}".format(net_d["nebulaid"], ar_id))
        if not out or "Address Range does not exist" in out:
            break
        time.sleep(2.5)

    if out and "Address Range does not exist" not in out:
        debug_log_print_ext("addr range removal unsuccessful", out)
        raise GeneralAPIError(out)

    decrease_net_size_db(netid, size)

    return True


def list_nodes_nebula():
    nodes_info_lock.acquire()
    nodes = copy.deepcopy(NODES_INFO)
    nodes_info_lock.release()

    return nodes


def info_node_nebula(nebulaid):
    nodes_info_lock.acquire()
    node = copy.deepcopy(NODES_INFO.get(nebulaid))
    nodes_info_lock.release()

    if not node:
        debug_log_print_ext("node with nebula id {0} doesn't exist in nebula".format(nebulaid))
        raise NoSuchObjectException("node with nebula id {0} doesn't nebula".format(nebulaid))
    return node


def info_nebulanet(nebulaid):
    nets_info_lock.acquire()
    net = copy.deepcopy(NETS_INFO.get(nebulaid))
    nets_info_lock.release()

    if not net:
        debug_log_print_ext("net with net id {0} doesn't exist".format(nebulaid))
        raise NoSuchObjectException("net with net id {0} doesn't exist".format(nebulaid))
    return net


def recursive_element_list(elem):
    children = list(elem)
    if children:
        subs = []
        for child in children:
            subs.append(recursive_element_list(child))

        tkeys = map(lambda a: a[0], subs)
        subs_d = {}
        for k, v in subs:

            # v xml je v jedne urovni vice elementu se stejnym jmenem
            if tkeys.count(k) > 1:
                arr = subs_d.get(k, [])
                arr.append(v)
                subs_d[k] = arr
            else:
                subs_d[k] = v

        # for k in subs_d.keys():
        #     if len(subs_d[k]) == 1:
        #         subs_d[k] = subs_d[k][0]

        return elem.tag, subs_d

    else:
        k, v = elem.tag, elem.text
        if k[-2:] == "ID" and v and k != "DEPLOY_ID":
            v = int(v)
            pass
        elif k == "SIZE" and v:
            v = int(v)
        elif k == "STATE" and v:
            v = int(v)
        elif k == "LCM_STATE" and v:
            v = int(v)
        return k, v


def list_nebulanets_xml():
    nets_info_lock.acquire()
    nets = copy.deepcopy(NETS_INFO)
    nets_info_lock.release()

    return nets


def nebulaid_to_vxlanid_mapping():
    vnets = list_nebulanets_xml()

    nebulaids2vxids = {}
    for i in vnets.iterkeys():
        if vnets[i]["VLAN"] != "1":
            continue
        nebulaids2vxids[i] = vnets[i]["VLAN_ID"]
    return nebulaids2vxids


def get_node_state_nebula(nebulaid):
    ni = info_node_nebula(nebulaid)
    vm_state = ni["STATE"]
    lcm_state = ni["LCM_STATE"]
    value = {"vm_state": NUM2VMSTATE[vm_state], "lcm_state": NUM2LCMSTATE[lcm_state],
             "STATE": NUM2VMSTATE[vm_state], "LCM_STATE": NUM2LCMSTATE[lcm_state],
             "state": NUM2VMSTATE[vm_state]}

    return value


def check_state_nebula(nebulaid, vmstate=None, lcmstate=None, tries=1):
    realvmstate = None
    reallcmstate = None
    change_condition = threading.Condition()
    with change_condition:
        cb = NotifyTask(node_ids=[], change_selector=None, towhat=None, howmany=1, notifycondition=change_condition)
        while tries >= 1:
            states = get_node_state_nebula(nebulaid)
            if vmstate:
                realvmstate = states["vm_state"]
            if lcmstate:
                reallcmstate = states["lcm_state"]

            if vmstate == realvmstate and lcmstate == reallcmstate:
                return True

            if tries == 1:
                debug_log_print_ext(
                        "attempted action isn't possible due to node being in wrong state (current: {0} ; needed: {1}".format(
                                (realvmstate, reallcmstate), (vmstate, lcmstate)))
                raise WrongStateForActionException("attempted action isn't possible due to node being in wrong state")
            tries -= 1

            callbacks_in_queue.put(cb)
            change_condition.wait()
    return True


def get_node_state(nodeid, selector=None):
    db_node_info = get_node_db(nodeid)

    platform = db_node_info["platform"]

    if platform == "nebula":
        value = get_node_state_nebula(db_node_info["internal_id"])

    else:
        # OpenStack
        pass

    if selector:
        return value[selector]

    return value


def list_nebula_images():
    try:
        out, stderr = run_cmd_e("oneimage list -x")
        tree = ET.fromstring(out)

        # root = tree.getroot()
        imgs = {}
        for img in tree:
            k, v = recursive_element_list(img)
            id = v['ID']
            imgs[id] = v
    except RuntimeError as e:
        debug_log_print(e)
        return {}
    return imgs



if __name__ == '__main__':
    poller = InfoPoller()
    poller.setDaemon(daemonic=True)
    debug_log_print("start poller")
    poller.start()
    debug_log_print("started poller")

    checker = CallbackChecker()
    checker.setDaemon(daemonic=True)
    checker.start()

    time.sleep(1)
    tdata.DB_CON = open_db2()
    with tdata.DB_CON:

        if len(sys.argv) >= 2 and sys.argv[1] == "server":
            #
            # callbackdispatcher = CallbackDispatcher()
            # callbackdispatcher.setDaemon(daemonic=True)
            # debug_log_print("start callback dispatcher")
            # callbackdispatcher.start()
            # debug_log_print("started callback dispatcher ")
            #
            # app.run('0.0.0.0', threaded=True)
            print "run cloud_api_flaskroutes instead"


        elif len(sys.argv) >= 2 and sys.argv[1] == "init":

            try:
                res_d = get_user("tester", verifybypass=True)
            except NoSuchObjectException:
                add_user("tester", "tester", isadmin=True)
                res_d = get_user("tester", verifybypass=True)

            res_d = get_user("tester", verifybypass=True)

            tdata.username = res_d["name"]
            tdata.isadmin = res_d["isadmin"]
            tdata.ownertag = "owner:{0}".format(res_d["name"])


            nodetmpl = '''CPU=$cpu
VCPU=$vcpu
MEMORY=$memory
DISK=[DEV_PREFIX=vd, IMAGE_ID=$image_id]
INPUT = [TYPE=tablet, BUS=usb]
GRAPHICS=[KEYMAP=en-us, LISTEN=0.0.0.0, TYPE=vnc, PASSWD="$vnc_passwd"]
OS=[ARCH=x86_64, BOOT=hd]
SCHED_REQUIREMENTS="(CLUSTER=\\"kypo-sitola\\")"
RAW=[DATA="<!-- RAW data follows: --><cpu mode='host-model'></cpu>",TYPE="kvm"]
CONTEXT=[DUMMY="dummy"]
'''

            default_node_values = dict(image_id=61,
                                       vnc_passwd="d3f4u1t_vNc.p4s5W0rD!",
                                       cluster=CLUSTER_NAME,
                                       cpu=1,
                                       vcpu=1,
                                       memory=512,
                                       )

            try:
                get_nodetemplate_db(templname="test_vm1")
            except NoSuchObjectException:
                add_nodetemplate_db(nodetmpl, "test_vm1", defaultvalues=json.dumps(default_node_values))

            nodeid1 = create_node("test_vm1")
            debug_log_print("node created:", nodeid1)
            nodeid2 = create_node("test_vm1")
            debug_log_print("node created:", nodeid2)

            time.sleep(60)

            debug_log_print(connect_nodes_nebula(nodeid1, nodeid2, None, None))
            debug_log_print(connect_nodes_nebula(nodeid1, nodeid2, None, None))
            debug_log_print(connect_nodes_nebula(nodeid2, nodeid1, None, None))
        else:
            res_d = get_user("tester", verifybypass=True)

            tdata.username = res_d["name"]
            tdata.isadmin = res_d["isadmin"]
            tdata.ownertag = "owner:{0}".format(res_d["name"])

            # debug_log_print(connect_nodes_nebula(1,2,None,None))
            # debug_log_print(connect_nodes_nebula(1,2,None,None))

            debug_print(get_nodes_db_for_output())
            debug_print(get_node_db_for_output(1))
            debug_print(get_network_db_for_output(1))
            debug_print(get_networks_db_for_output())

            # debug_print(get_interfaces_db(nodeid=2))
            #
            # debug_print(get_node_db_and_internal(2))
            #
            # add_user("user", "user", isadmin=False)

            # debug_log_print("Nodes DB:", get_nodes_db(tags=["LMN","user:jirka"]))

            # add_tag_node(["ZZZZZ"], 1)
            # add_tag_node(["LMN","user:jirka"], 2)
            add_tag_node(["SMN"], 1)
            # add_tag_node(["LMN","user:donald"], 3)
            add_tag_node(["SMN"], 1)

            # debug_log_print("Nodes DB:", get_nodes_db(tags=["SMN"]))
            #
            # # debug_log_print("Nets DB:", get_network_db(177))
            #
            # debug_log_print("Intfs DB:", get_interfaces_db())

            # create_tag("LMN")
            # create_tag("SMN")
            # create_tag("user:jirka")
            # create_tag("user:donald")

            # print db_con, db_cur
            #
            # db_con.close()
            # debug_print("main:", get_nodes_db())
            # debug_print("more:", info_nebulanet(225))
            # debug_print("vxids", get_used_vxids_db())



            # add_new_networks_db()
            # debug_log_print(list_vxlan_nebulanets()[188])
            # debug_log_print("Nets DB:", get_network_db(177))
            # debug_log_print(get_tags_node(3))





            # debug_log_print(get_nodetemplate_db(1))
            #
            # ni = int(info_node_nebula(407)["STA1TE"])
            # # for key in  ni.keys():
            # #     if "STAT" in key:
            # #         print key, ni[key]
            #
            #
            # print NUM2STATE[ni]

            #
            # print STATE2NUM
            # debug_log_print(list_nodes_nebula())


            # tdata.DB_CON.close()
            # pprint.pprint(list_templates_nebula())

    time.sleep(2)
