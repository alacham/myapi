# -*- coding: utf-8 -*-
from __future__ import division
#
import sys
# reload(sys)
# sys.setdefaultencoding('utf8')

import os
import psycopg2
import psycopg2.extras
psycopg2.extras.register_default_json(loads=lambda x: x)
import time
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import re
import random
import string
import json
import xmlrpclib
import multiprocessing
import time
import threading
import pprint
import copy
import requests
import hashlib
import binascii
import logging

from cloud_api_settings import *
from cloud_api_nebulaconstants import *

logging.basicConfig(filename=LOGGING_PATH,level=LOGLEVEL)

from datetime import datetime, timedelta


def totimestamp(dt, epoch=datetime(1970,1,1)):
    td = dt - epoch
    # return td.total_seconds()
    return (td.microseconds + (td.seconds + td.days * 86400) * 10**6) / 10**6


import Queue

tdata = threading.local() # thread local data - mainly for username
tdata.extended_error_log = ""
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
    tdata.extended_error_log = "\n".join((tdata.extended_error_log, topr))
    if DEBUG_PRINTS:
        print topr




callback_send_queue = Queue.Queue()

callbacks_in_queue = Queue.Queue()


NODES_INFO = {}
NETS_INFO = {}

debug_log_print("init")
nodes_info_lock = threading.Lock()
nodes_info_lock.acquire()

nets_info_lock = threading.Lock()
nets_info_lock.acquire()


class InfoPoller(threading.Thread):

    def run(self):
        tdata.DB_CON = open_db2()
        tdata.isadmin = True

        with tdata.DB_CON:
            global NODES_INFO
            global NETS_INFO

            NODES_INFO = self.list_nodes_nebula()
            # debug_log_print(NODES_INFO)
            nodes_info_lock.release()
            NETS_INFO = self.list_nebulanets_xml()
            nets_info_lock.release()

            time.sleep(2)

            callbacks_to_check = []
            resend_notify_signal = []

            # main checking loop
            while True:

                # obtain new hooks from queue
                while True:
                    try:
                        callback = callbacks_in_queue.get_nowait()
                        callbacks_to_check.append(callback)
                    except Queue.Empty:
                        break

                nodes = self.list_nodes_nebula()
                nodes_info_lock.acquire()
                NODES_INFO = nodes
                nodes_info_lock.release()

                newcallbacks = []
                for callback in callbacks_to_check:
                    should_notify = callback.check_changes(nebuladict=nodes)
                    if should_notify:
                        if callback.notifycondition:
                            resend_notify_signal.append(callback.notifycondition)

                    if not callback.finished:
                        newcallbacks.append(callback)

                callbacks_to_check = newcallbacks

                time.sleep(2)

                while True:
                    try:
                        condition = resend_notify_signal.pop()
                        with condition:
                            condition.notifyAll()
                    except IndexError:
                        break

                nets = self.list_nebulanets_xml()
                nets_info_lock.acquire()
                NETS_INFO = nets
                nets_info_lock.release()

                time.sleep(2)

    def list_nodes_nebula(self):
        try:
            out, stderr = execute_cmd_e("onevm list -x")
            tree = ET.fromstring(out)

            #root = tree.getroot()
            vms = {}
            for vm in tree:
                k,v = recursive_element_list(vm)
                id = v['ID']
                vms[id] = v
        except RuntimeError as e:
            debug_log_print(e)
            return {}
        return vms

    def list_nebulanets_xml(self):
        try:
            out, stderr = execute_cmd_e("onevnet list -x")
            tree = ET.fromstring(out)

            #root = tree.getroot()
            vnets = {}
            for vnet in tree:
                k,v = recursive_element_list(vnet)
                id = v['ID']

                ars_d = {} #address ranges
                if v['AR_POOL'] is not None:
                    if isinstance(v['AR_POOL']['AR'],list):
                        ars = v['AR_POOL']['AR']
                        for ar in ars:
                            ars_d[ar['AR_ID']] = ar
                    else:
                        ars_d[v['AR_POOL']['AR']['AR_ID']] = v['AR_POOL']['AR']

                    for k2,v2 in ars_d.items():
                        if "ALLOCATED" in v2 and v2["ALLOCATED"] is not None:
                            allocated = map(int, v2["ALLOCATED"].split())
                            alloc_d = {}

                            for i in range(0,int(len(allocated)/2)): # TODO to int by melo byt zbytecne, ale kvuli nejakemu bugu neni
                                # viz binary_magic = 0x0000001000000000 | (vid & 0xFFFFFFFF)
                                # v https://github.com/burgosz/opennebula-sunstone-shib/blob/master/ruby/onedb/local/4.5.80_to_4.7.80.rb
                                alloc_d[allocated[i*2]] = allocated[i*2+1] & 0x00000000FFFFFFFF
                            v2["ALLOCATED"] = alloc_d

                    v['AR_POOL'] = ars_d

                vnets[id] =v
        except RuntimeError as e:
            debug_log_print(e)
            return {}
        return vnets


class CallbackSender(threading.Thread):

    def run(self):

        while True:

            tosend = callback_send_queue.get()

            r = requests.post(tosend["url"], json=tosend["data"])

            if r.status_code != 200:
                debug_log_print("Error sending callback", tosend)

            callback_send_queue.task_done()



class MacAddress(object):

    def __init__(self,macplainstr):
        self.nummeric = int(macplainstr, 16)


    def __str__(self):
        plainstr = '%012x' % self.nummeric
        outstr = []
        for i in range(len(plainstr)):
            outstr.append(plainstr[i])
            if i % 2 == 0 and i != 0:
                outstr.append(":")
        return "".join(outstr)

    def __repr__(self):
        return self.__str__()


    @classmethod
    def from_parts(cls, macprefix=None, macsuffix=None, checkuser=False, checkflat=False, delim=":"):
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

        #TODO check for duplicates

        macplain = macprefix+macmiddle+macsuffix
        macobj = MacAddress(macplain)

        return macobj

    @classmethod
    def from_delimited(cls,macstr, delim=":"):
        parts = macstr.split(delim)
        if len(parts) != 6:
            raise BadMacAddrException
        try:
            for p in parts:
                if not 0 <= int(p, base=16) <= 255:
                    raise BadMacAddrException
        except:
            raise BadMacAddrException
        return MacAddress(macstr.replace(delim,""))

    @classmethod
    def from_nummeric(cls, num):
        plainstr = '%012x' % num
        return MacAddress(plainstr)


class KypoError(Exception):
    def __init__(self, arg=""):
        self.message = arg

class DuplicateNameException(KypoError):
    pass

class NoSuchObjectException(KypoError):
    pass

class BadMacAddrException(KypoError):
    pass

class PrivilegeException(KypoError):
    pass

class WrongStateForActionException(KypoError):
    pass


def try_more_time(start_time, max_time):
    if max_time == 0:
        return True

    if (time.time() - start_time) > max_time:
        return False
    else:
        return True



class NotifyTask(object):
    active_hooks = {}

    def __init__(self, node_ids=None, change_selector=None, towhat=None, howmany=0, howlong=0, notifycondition=None, notifyaddr=None):
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
            allnodes = get_nodes_db()
            for nid in node_ids:
                if nid not in allnodes:
                    debug_log_print_ext("notifytask: Entered Id doesn't belong to any id")
                    continue
                try:
                    if allnodes[nid]["platform"] == "nebula" and allnodes[nid]["internal_id"]:
                        self.nebulaidstocheck.add(allnodes[nid]["internal_id"])
                        self.nebulaid_2_dbid[allnodes[nid]["internal_id"]] = nid
                    else: # TODO OpenStack
                        pass
                except Exception as e:
                    debug_log_print_ext("NotifyTask: get internal id error: "+e)


        if (not self.nebulaidstocheck and not self.openstackidstocheck) or (not notifycondition and not notifyaddr) or not self.change_selector:
            self.finished = True
            debug_log("NotifyTask wouldn't check any nodes")
        else:
            while True:
                self.taskid = random.randint(0, 2**32 -1)
                if not self.taskid in self.active_hooks.keys():
                    self.active_hooks[self.taskid] = self
                    break
            if self.nebulaidstocheck:
                self.previous_nebula = {}



    """
        checks if there are matching changes and possibly notifies about it
        :returns True to signal that it's to safe discard this check, False otherwise
    """
    def check_nebulanodes_changes(self, current_nebuladict):
        self.changes_n = {}
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
                self.changes_n[self.nebulaid_2_dbid[nebulaid]] = "nonexistent"
                idstoremove.add(nebulaid)
                continue

            prevnodestate = self.preious_nebula.get(nebulaid,{})
            prevval = prevnodestate.get(self.change_selector,None)

            if prevval == curval:
                continue

            if curval == self.towhat or self.towhat == None:
                self.changes_n[self.nebulaid_2_dbid[nebulaid]] = curval

        self.previous_nebula = current_nebuladict
        self.nebulaidstocheck.difference_update(idstoremove)

        if self.changes_n:
            if self.notifycondition:
                with self.notifycondition:
                    self.notifycondition.notifyAll()
            if self.notifyaddr:
                datamsg = {"status": "ok", "type": "callback update", "changes": self.changes_n, "callbackid": self.taskid }
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





# def check_condition(test_callable, test_args, check_result_function, check_args, reaction, max_attempt_time, once=False):
#
#     def testfunction():
#         starttime = time.time()
#         end_condition = False
#
#         while end_condition == False and try_more_time(starttime, max_attempt_time):
#             results = test_callable(**test_args)
#
#             end_condition = check_result_function(results, **check_args)
#
#
#     return testfunction

def check_user_privilege_node(nodeid):
    tags = get_tags_node(nodeid)
    usertag = "owner:{0]".format(tdata.username)
    if usertag not in tags:
        raise PrivilegeException("you're not owner of this node")

def check_user_privilege_net(netid):
    tags = get_tags_net(netid)
    usertag = "owner:{0]".format(tdata.username)
    if usertag not in tags:
        raise PrivilegeException("you're not owner of this net")


def execute_cmd(cmd):
    """Execute commnad with subprocess and return its stdout."""

    handler = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    stdout, stderr = handler.communicate()

    # Check the exit code
    if handler.returncode:
        # raise RuntimeError("Error during '%s' execution. \nSTDERR: %s"     % (cmd, stdout))
        return stderr+stdout, stderr
    # Return stdout
    return stdout, stderr

def execute_cmd_e(cmd):
    """Execute commnad with subprocess and return its stdout."""

    handler = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    stdout, stderr = handler.communicate()

    # Check the exit code
    if handler.returncode:
        raise RuntimeError("Error during '%s' execution. \nSTDERR: %s"     % (cmd, stdout))
    # Return stdout
    return stdout, stderr

def open_db2():
    try:
        # TODO predelat do os.environ
        #DATABASE = os.environ["CLOUD_API_DB2"]
        USER = os.environ["CLOUD_API_DB_USER"]
    except KeyError:
        raise RuntimeError("CLOUD_API_DB or CLOUD_API_DB_USER environment variable do not exist.")

    debug_log_print("trying to connect database: ",( DATABASE, USER))
    try:
        db_con = psycopg2.connect(database=DATABASE, user=USER)
        db_con.autocommit = True
    except psycopg2.DatabaseError as e:
        debug_log_print(repr(e))
        raise

    return db_con


def get_network_db(netid):
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        db_cur.execute("SELECT * from nebula_networks WHERE id = %s ;", (netid,))
        net_dict = db_cur.fetchone()
    if not net_dict:
        raise NoSuchObjectException("no such network id: {0}".format(netid))

    if not tdata.isadmin:
        tags = get_tags_net(netid)
        if not tdata.ownertag in tags:
            raise PrivilegeException("can't access network id: {0}".format(netid))

    return net_dict

def get_network_db_and_internal(netid):

    net_d = get_network_db(netid)
    internalvalue = net_d["nebulaid"]
    try:
        net_d["internal_info"] = info_nebulanet(internalvalue)
    except NoSuchObjectException:
        net_d["internal_info"] = None

    return net_d



def get_nodes_db_and_internal(tags=None, nodeids=None):

    nodes_d = get_nodes_db(tags, nodeids)

    nebulanodes = list_nodes_nebula()

    for node in nodes_d.values():
        internalid = node.get("internal_id")

        if node["platform"] == "nebula":
            internalvalue = nebulanodes.get(internalid, None)
            node["internal_info"] = internalvalue
            state = NUM2VMSTATE.get(nebulanodes.get(internalid,{}).get("STATE"),"UNKNOWN")
            if state != node["state"]:
                update_node_db(node["id"],node)
                node["state"] = state
        else:
            #OpenStack
            pass

    return nodes_d

def get_nodes_db(tags=None, nodeids=None):

    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        if tags:
            tags = set(tags)
            if not tdata.isadmin:
                tags.add(tdata.ownertag)
            tag_placeholder = ", ".join([ "%s" for _ in tags])

            querystart = "SELECT n.* from nodes n, node_taggings nt, tagwords t WHERE t.tag in ("

            queryend = ") AND nt.tag_id = t.id AND n.id = nt.node_id GROUP BY n.id HAVING COUNT( n.id ) = %s ;"

            db_cur.execute(querystart + tag_placeholder + queryend, list(tags) + [len(tags)])
        else:
            if nodeids:
                if not tdata.isadmin:
                    nodeids_placeholder = ", ".join([ "%s" for _ in nodeids])

                    querystart = "SELECT n.* from nodes n, node_taggings nt, tagwords t WHERE  n.id in ("

                    queryend = ") AND t.tag=%s AND nt.tag_id = t.id AND n.id = nt.node_id ;"
                    db_cur.execute(querystart + nodeids_placeholder + queryend, nodeids+tdata.ownertag)
                else:
                    nodeids_placeholder = ", ".join([ "%s" for _ in nodeids])

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
            db_cur.execute("SELECT * from nebula_networks ;")
        else:
            tags = set(tags)
            if not tdata.isadmin:
                tags.add(tdata.ownertag)

            tag_placeholder = ", ".join([ "%s" for _ in tags])

            querystart = "SELECT n.* from nebula_networks n, net_taggings nt, tagwords t WHERE t.tag in ("

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
    for k,v in nets_d.iteritems():
        internalid = v["nebulaid"]
        v["internalinfo"] = nebulanets_d.get(internalid, None)

        if typeselect and v["type"] == typeselect:
            out_d[k] = v

    if typeselect:
        return out_d
    return nets_d



def get_used_vxids_db():
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("SELECT vid from nebula_networks ;")
        vxids = map(lambda a: a[0], db_cur.fetchall())
    return vxids


def get_node_db(node_id):
    db_con = tdata.DB_CON

    if not tdata.isadmin:
        tags = get_tags_node(node_id)
        if tdata.ownertag not in tags:
            raise PrivilegeException("you cannot access this node")

    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        db_cur.execute("SELECT * from nodes WHERE id = %s ;", (node_id,))
        node_d = db_cur.fetchone()

    if not node_d:
        raise NoSuchObjectException("Node with id: %d not found" % (node_id))

    return node_d

def get_node_db_and_internal(nodeid):
    node = get_node_db(nodeid)

    if node["platform"] == "nebula":
        internalvalue = node["internal_id"]
        try:
            node["internal_info"] = info_node_nebula(internalvalue)
        except NoSuchObjectException:
            node["internal_info"] = None
            state = "UNKNOWN"
        else:
            node["internal_info"] = internalvalue
            state = NUM2VMSTATE.get(internalvalue.get("STATE"),"UNKNOWN")
        if state != node["state"]:
            update_node_db(node["id"],node)
            node["state"] = state
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

def get_interfaces_db(netid=None , nodeid=None):
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        if not netid and not nodeid:
            db_cur.execute("SELECT * from nebula_interfaces;")
        elif netid and nodeid:
            db_cur.execute("SELECT * from nebula_interfaces WHERE net_id=%s AND node_id=%s ;", (netid, nodeid))
        elif netid:
            db_cur.execute("SELECT * from nebula_interfaces WHERE net_id=%s ;", (netid,))
        else:
            db_cur.execute("SELECT * from nebula_interfaces WHERE node_id=%s ;", (nodeid,))

        results = db_cur.fetchall()
    return results

def get_interface_db(intfid):
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        db_cur.execute("SELECT * from nebula_interfaces WHERE id=%s ;", (intfid,))
        res_d = db_cur.fetchone()
    if not res_d:
        raise NoSuchObjectException("no interface with such id")
    return res_d



def get_nodetemplate_db(templid=None, templname=None,extractdefaults=True):

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

    if not tdata.isadmin and templ_d["userid"] and  templ_d["userid"] != tdata.userid:
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
        node_tuple = (node_d.get("name",None), node_d.get("internal_id", None), node_d.get("state","ACTIVE"), datetime.utcnow(), node_d["platform"] )
        db_cur.execute("INSERT into nodes (name, internal_id, state, lastchange, platform) VALUES ( %s, %s, %s, %s, %s) RETURNING id;", node_tuple)
        try:
            nodeid = db_cur.fetchone()[0]
        except psycopg2.IntegrityError:
            debug_log("Such node name (%s) already exists in DB." % (node_d["name"],))
            raise DuplicateNameException("Such node name (%s) already exists in DB." % (node_d["name"],))

    return nodeid

def delete_node_db(nodeid):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("DELETE from nodes WHERE id = %s ;", (nodeid,))


def delete_net_db(netid):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("DELETE from nebula_networks WHERE id = %s ;", (netid,))



def update_node_db(node_id, node_d):

    # check_user_privilege_node(node_id)

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        node_props = [node_d["name"], node_d["internal_id"], node_d["state"], datetime.utcnow(), node_d["platform"] ]

        db_cur.execute("UPDATE nodes SET name=%s, internal_id=%s, state=%s, lastchange=%s, platform=%s WHERE id=%s ;", node_props+[node_id])

def increase_net_use_db(netid,howmuch=1):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("UPDATE nebula_networks SET used=used+%s WHERE id=%s ;", (howmuch, netid))

def decrease_net_use_db(netid,howmuch=1):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("UPDATE nebula_networks SET used=used-%s WHERE id=%s ;", (howmuch, netid))

def increase_net_size_db(netid,howmuch=1):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("UPDATE nebula_networks SET size=size+%s WHERE id=%s ;", (howmuch, netid))

def decrease_net_size_db(netid,howmuch=1):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("UPDATE nebula_networks SET size=size-%s WHERE id=%s ;", (howmuch, netid))


def add_network_db(net_d, type="pt2pt", size=2, shaping="", startmac=None):
    if isinstance(startmac, MacAddress):
        startmac = str(startmac)

    db_con = tdata.DB_CON
    net_tuple = [net_d["nebulaid"], size, net_d.get("used",0), net_d["vxid"], type, shaping, datetime.utcnow(), startmac]

    with db_con.cursor() as db_cur:
        # if startmac:
        #     debug_log_print(startmac, startmac.nummeric, str(startmac))
        #     debug_log_print(net_tuple+[startmac])
        db_cur.execute("INSERT into nebula_networks (nebulaid,size,used,vid,type,shaping,reservedsince,startmac) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;" ,net_tuple)
        # else:
        #     db_cur.execute("INSERT into nebula_networks (nebulaid,size,used,vid,type,shaping,reservedsince) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;" ,net_tuple)
        netid = db_cur.fetchone()[0]



    add_tag_network(tdata.ownertag,netid)

    return netid


def add_nodetemplate_db(templstring,name,defaultvalues=None,defaultuse=False,userid=None,user=None, platform="nebula"):

    if user and isinstance(user, basestring):
        userid = get_user(username=user)["id"]


    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        try:
            db_cur.execute("INSERT into templates (name,template,defaultvalues,defaultuse,userid,platform) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;" ,(name,templstring,defaultvalues,defaultuse,userid,platform))
            dbid = db_cur.fetchone()[0]
        except psycopg2.IntegrityError  as e:
            debug_log_print_ext("template with name %s already exists" % (name,), e)
            raise DuplicateNameException("template with name %s already exists" % (name,))
    return dbid


def create_tag(tagname):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        try:
            db_cur.execute("INSERT into tagwords (tag) VALUES (%s) ;" ,(tagname,))
        except psycopg2.IntegrityError:
            raise DuplicateNameException("tag with name {0} already exists".format(tagname))


def add_tag_node(tags, node):
    if isinstance(tags, basestring):
        tags = [tags]

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        for tag in tags:
            try:
                db_cur.execute("INSERT into node_taggings (node_id, tag_id) VALUES (%s, (SELECT id from tagwords WHERE tag =%s)) ;" ,(node, tag))
            except psycopg2.IntegrityError as e:
                if "violates foreign key constraint" in e:
                    debug_log_print("such node id doesn't exist")
                    raise NoSuchObjectException("such node id doesn't exist")
                elif 'null value in column "tag_id" violates not-null constraint' in e:
                    debug_log_print("such tag doesn't exist")
                    raise DuplicateNameException("such tag doesn't exist")
                else:
                    debug_log_print("add node integrity error: %s" %(e,))
                    raise KypoError("add node integrity error: %s" %(e,))

def remove_tag_node(tags, node):
    if isinstance(tags, basestring):
        tags = [tags]

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        for tag in tags:
            try:
                db_cur.execute("INSERT into node_taggings (node_id, tag_id) VALUES (%s, (SELECT id from tagwords WHERE tag =%s)) ;" ,(node, tag))
            except psycopg2.IntegrityError as e:
                if "violates foreign key constraint" in e:
                    debug_log_print("such node id doesn't exist")
                    raise NoSuchObjectException("such node id doesn't exist")
                elif 'null value in column "tag_id" violates not-null constraint' in e:
                    debug_log_print("such tag doesn't exist")
                    raise DuplicateNameException("such tag doesn't exist")
                else:
                    debug_log_print("add node integrity error: %s" %(e,))
                    raise KypoError("add node integrity error: %s" %(e,))




def add_tag_network(tags, net):
    if isinstance(tags, basestring):
        tags = [tags]

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        for tag in tags:
            try:
                db_cur.execute("INSERT into net_taggings (net_id, tag_id) VALUES (%s, (SELECT id FROM tagwords WHERE tag=%s)) ;" ,(net,tag))
            except psycopg2.IntegrityError as e:
                if "violates foreign key constraint" in e:
                    debug_log_print("such net id doesn't exist")
                    raise NoSuchObjectException("such net id doesn't exist")

                elif 'null value in column "tag_id" violates not-null constraint' in e:
                    debug_log_print("such tag doesn't exist")
                    raise DuplicateNameException("such tag doesn't exist")
                else:
                    debug_log_print("add net integrity error: %s" %(e,))
                    raise KypoError("add net integrity error: %s" %(e,))

def add_user(username, password, isadmin=False, kypouser=None):

    saltstr = "".join(random.choice(SALTCHARS) for _ in range(SALTLEN))
    derivedkey = hashlib.pbkdf2_hmac('sha256', password, saltstr, 100000)
    hexalified = binascii.hexlify(derivedkey)

    inserttuple = (username, hexalified, saltstr, isadmin, kypouser)

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        try:
            db_cur.execute("INSERT into users (name, password, salt, isadmin, kypouser) VALUES (%s, %s, %s, %s, %s) ;" , inserttuple)
        except psycopg2.IntegrityError as e:
            debug_log_print_ext("user couldn't be added, probably duplicate;\n %s" %(e,))
            raise KypoError("user couldn't be added, probably duplicate")

    create_tag("owner:{0}".format(username))
    return True

def get_user(username):
    db_con = tdata.DB_CON
    with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
        db_cur.execute("SELECT id, name, password, salt, isadmin, kypouser FROM users WHERE name=%s ;" , [username])
        res_d = db_cur.fetchone()
    return res_d


def get_tags():
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("SELECT tag FROM tagwords ;")
        tags = db_cur.fetchall()
    tags = map(lambda a: a[0], tags)
    return tags

def get_tags_node(nodeid):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("SELECT tag FROM node_taggings, tagwords WHERE node_id=%s and tag_id=id ;" ,(nodeid,))
        tags = db_cur.fetchall()
    tags = map(lambda a: a[0], tags)
    return tags

def get_tags_net(netid):
    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        db_cur.execute("SELECT tag FROM net_taggings, tagwords WHERE net_id=%s and tag_id=id ;" ,(netid,))
        tags = db_cur.fetchall()
    tags = map(lambda a: a[0], tags)
    return tags



def add_new_networks_db():
    def get_networks_db():
        db_con = tdata.DB_CON

        with db_con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as db_cur:
            db_cur.execute("SELECT * from nebula_networks;")
            net_ds = db_cur.fetchall()

        nets = {}
        for nd in net_ds:
            nets[nd["nebulaid"]] = nd

        return nets

    dbnets = get_networks_db()

    debug_print("puvodni site")
    debug_print(dbnets)
    nebulanets = list_vxlan_nebulanets()
    debug_print("nebula site")
    debug_print(nebulanets)

    for k in nebulanets.keys():
        if k not in dbnets:
            n = nebulanets[k]
            n["id"] = n["ID"]
            n["used"] = n["USED_LEASES"]
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
        db_cur.execute("DELETE FROM nebula_interfaces WHERE id=%s ;" ,(intfid,))
    return True

def remove_disconnect_interface(intfid):
    intf_d = get_interface_db(intfid)

    net_d = get_network_db(intf_d["net_id"])

    node_d = get_node_db(intf_d["node_id"])

    check_state_nebula(intf_d["node_id"],lcmstate="RUNNING",tries=2)

    out, stderr = execute_cmd("onevm  nic-detach  {0} --network {1}".format(node_d["internal_id"], net_d["nebulaid"]))
    if out:
        debug_log_print("dettaching nic in nebula unsuccessful", "onevm  nic-detach  {0} --network {1}".format(node_d["internal_id"], net_d["nebulaid"]), out)
        raise KypoError("dettaching nic in nebula unsuccessful")
    delete_nebulainterface_db(intfid)


def create_vxlan_nebulanet(mac, size=None, addars=None, nettype="pt2pt"):
    temp_net_f = tempfile.NamedTemporaryFile(delete=False)

    with open(TEMPLATE_PATH+VXLAN_TEMPLATE_FILE, "r") as nt:
        nettemplate = string.Template(nt.read())

    used_vlanids = list_vxlan_nebulanets().keys()

    vxid = 0
    while True:
        #TODO potentially infinite loop, all may be used up
        vxid = random.randint(VXIDSTART,VXIDEND)
        if str(vxid) not in used_vlanids:
            break

    if not size:
        size = 1

    combinedsize = size

    subst_dict = { "vlanid" : vxid }
    netstr = nettemplate.safe_substitute(subst_dict)
    netstr += ADDRESS_RANGE.format(mac,size) + "\n"

    if addars:
        for mac, size in addars:
            netstr += ADDRESS_RANGE.format(mac,size) + "\n"
            combinedsize += size

    temp_net_f.write(netstr)
    temp_net_f.flush()
    temp_net_f.close()
    tname = temp_net_f.name

    debug_log_print("onevnet -c %s create %s" % (CLUSTER_NAME, tname))
    out, stderr = execute_cmd("onevnet create -c {0}  {1}".format(CLUSTER_NAME, tname))

    if "ID:" == out[:3]:
        os.remove(tname)
    else:
        debug_log_print_ext(out)
        raise KypoError(out)

    nebulanetid = int(out.split()[1])

    net_d = {"nebulaid":nebulanetid, "vxid": vxid , "used": 0 }

    netid = add_network_db(net_d,nettype,size=combinedsize)

    debug_log_print("Nebula net %d added as network with db id %d " % (nebulanetid, netid))

    return netid




def create_link(mac1,mac2):
    temp_net_f = tempfile.NamedTemporaryFile(delete=False)

    with open(TEMPLATE_PATH+VXLAN_TEMPLATE_FILE, "r") as nt:
        nettemplate = string.Template(nt.read())

    #used_vlanids = map(lambda a: a.get('bridge').replace("onebr0-vlan",""),list_nebulanets())
    used_vlanids = list_vxlan_nebulanets().keys()

    vxid = 0
    while True:
        #TODO potentially infinite loop, all may be used
        vxid = random.randint(VXIDSTART,VXIDEND)
        if str(vxid) not in used_vlanids:
            break


    subst_dict = { "vlanid" : vxid }

    netstr = nettemplate.safe_substitute(subst_dict)

    netstr += ADDRESS_RANGE.format(mac1,1) + "\n"
    netstr += ADDRESS_RANGE.format(mac2,2) + "\n"

    temp_net_f.write(netstr)
    temp_net_f.flush()
    temp_net_f.close()
    tname = temp_net_f.name

    debug_log_print("onevnet -c %s create %s" % (CLUSTER_NAME, tname))
    out, stderr = execute_cmd("onevnet create -c {0}  {1}".format(CLUSTER_NAME, tname))

    if "ID:" == out[:3]:
        os.remove(tname)
    else:
        debug_log(out)
        raise KypoError(out)

    nebulanetid = int(out.split()[1])

    net_d = {"nebulaid":nebulanetid, "vxid": vxid , "used": 0}

    netid = add_network_db(net_d,"pt2pt",size=2)

    debug_log_print("Nebula net %d added as network with db id %d " % (nebulanetid, netid))

    return netid


def create_publicflat_nebulanet(size=254, startmac=None):
    temp_net_f = tempfile.NamedTemporaryFile(delete=False)

    with open(TEMPLATE_PATH+PUBLICLAN_TEMPLATE_FILE, "r") as nt:
        nettemplate = string.Template(nt.read())

    nebulanets = list_nebulanets_xml()
    while True:
        lanid = random.randint(0,10000)
        name = PUBLIC_NET_NAME_TEMPL.format(lanid)

        nextiter = False
        for v in nebulanets.itervalues():
            if  name == v['NAME']:
                nextiter = True
                break
        if not nextiter:
            break

    subst_dict = { "lanid" : lanid , "lanname":name}

    if not startmac:
        startmac = MacAddress.from_parts(macprefix=FLAT_MAC_PREFIX, macsuffix="01")

    netstr = nettemplate.safe_substitute(subst_dict)
    netstr += ADDRESS_RANGE.format(startmac,size) + "\n"

    temp_net_f.write(netstr)
    temp_net_f.flush()
    temp_net_f.close()
    tname = temp_net_f.name

    debug_log_print("onevnet -c %s create %s" % (CLUSTER_NAME, tname))
    out, stderr = execute_cmd("onevnet create -c {0}  {1}".format(CLUSTER_NAME, tname))

    if "ID:" == out[:3]:
        os.remove(tname)
    else:
        debug_log(out)
        raise KypoError(out)

    nebulanetid = int(out.split()[1])

    net_d = {"id":nebulanetid, "vxid": None , "used": 0 }

    netid = add_network_db(net_d,"public",size=size,startmac=startmac)

    return netid



def attach_node_to_net(info_d, netid, waitforcompletion=False):
    if info_d["platform"] == "nebula":
        result=nebula_attach_node_to_net(info_d, netid, waitforcompletion=waitforcompletion)
    else:
        ## TODO openstack
        result=None
    return result

#TODO FIX!
def nebula_attach_node_to_net(info_d, netid, waitforcompletion=False):

    net_d = get_network_db(netid)
    if not net_d["nebulaid"]:
        raise KypoError("network wasn't properly initialized")
    nebulanetid = net_d["nebulaid"]

    # TODO - vyradit? used z db porusuje to x tou normu, muzu ziskat z interfaces - proc ne?
    if net_d["size"] <= net_d["used"]:
        raise KypoError("network size is not enough")

    db_con = tdata.DB_CON
    with db_con.cursor() as db_cur:
        intf_tuple = (info_d["id"], info_d.get("mac_addr"), info_d.get("ip", None), netid, info_d.get("shaping", "") )
        isok = True
        try:
            db_cur.execute("INSERT into nebula_interfaces (node_id, mac_addr, ip_addr, net_id, shaping) VALUES (%s, %s, %s, %s, %s) RETURNING id;", intf_tuple)
            dbid = db_cur.fetchone()[0]
        except psycopg2.IntegrityError as e:
            debug_log("nebula_attach_node_to_net - INSERT" + str(intf_tuple))
            raise KypoError(e + str(intf_tuple))

    intid = info_d["internal_id"]
    out, stderr = execute_cmd("onevm nic-attach {0}  --network {1}".format(intid, nebulanetid))
    debug_log_print("onevm nic-attach {0}  --network {1}".format(intid, nebulanetid))

    if out: #pri uspechu se nepise nic, jinak ano
        delete_nebulainterface_db(dbid)
        debug_log(out)
        raise KypoError(out)
    increase_net_use_db(netid,howmuch=1)

    if waitforcompletion:
        change_condition = threading.Condition()
        with change_condition:
            cb = NotifyTask(node_ids=[info_d["node_id"]], change_selector="LCM_STATE", towhat=LCMSTATE2NUM["HOTPLUG_NIC"], howmany=1, notifycondition=change_condition)
            callbacks_in_queue.put(cb)
            while True:
                nebulanode = info_node_nebula(intid)
                attached_netids = map(lambda a: a["NETOWRK_ID"], nebulanode["TEMPLATE"]["NIC"])
                if nebulanode["LCM_STATE"] == LCMSTATE2NUM["HOTPLUG_NIC"] or (nebulanode["LCM_STATE"] == LCMSTATE2NUM["RUNNING"] and netid in attached_netids):
                    break
                else:
                    change_condition.wait()

    # TODO: spravne zapsat mac adresu az ted


    return dbid



def change_node_state(nodeid, whattodo, waitforit=True):
    OPTIONS = [ "hold", "shutdown", "stop", "resume"]
    VM_STATE=["INIT", "PENDING", "HOLD", "ACTIVE", "STOPPED", "SUSPENDED", "DONE", "FAILED", "POWEROFF", "UNDEPLOYED"]

    state_action = { ("POWEROFF","LCM_INIT"): ["resume"],
                     ("ACTIVE","RUNNING"): ["stop","suspend","poweroff","undeploy","reboot"],
                     ("STOPPED","LCM_INIT"): ["resume"],
                     ("UNDEPLOYED","LCM_INIT"): ["resume"],
                     ("SUSPENDED","LCM_INIT"): ["resume"]}

    wanted_lcmstate_after_action = { "resume" : "RUNNING",
                                      "stop" : "LCM_INIT",
                                      "suspend" : "LCM_INIT",
                                      "poweroff" : "LCM_INIT",
                                      "undeploy" : "LCM_INIT",
                                      "reboot" : "RUNNING" }
    wanted_vmstate_after_action = { "resume" : "ACTIVE",
                                      "stop" : "STOPPED",
                                      "suspend" : "SUSPENDED",
                                      "poweroff" : "POWEROFF",
                                      "undeploy" :"UNDEPLOYED",
                                      "reboot" : "ACTIVE" }

    node_d = get_node_db(nodeid)

    if node_d["platform"] == "nebula":

        states_d = get_node_state_nebula(node_d["internal_id"])

        statetuple = (states_d["vm_state"],states_d["lcm_state"])

        if statetuple in state_action:
            if whattodo in state_action[statetuple]:
                out, stderr = execute_cmd("onevm %s %s" % (node_d["internal_id"], whattodo))
                if out:
                    debug_log_print("error changing state","onevm %s %s" % (node_d["internal_id"], whattodo), out)
                    raise KypoError("error changing state"+ out)

                if waitforit:
                    change_condition = threading.Condition()
                    with change_condition:
                        cb = NotifyTask(node_ids=[nodeid], change_selector="LCM_STATE", towhat=LCMSTATE2NUM[wanted_lcmstate_after_action[whattodo]], howmany=1, notifycondition=change_condition)
                        callbacks_in_queue.put(cb)
                        while True:
                            if get_node_state_nebula(node_d["internal_id"],"LCM_STATE" ) == wanted_lcmstate_after_action[whattodo] :
                                break
                            else:
                                change_condition.wait()

            else:
                debug_log_print("command %s not possible in vm state: %s , lcm state %s" % (whattodo, states_d["vm_state"],states_d["lcm_state"]))
                raise KypoError("command %s not possible in vm state: %s , lcm state %s" % (whattodo, states_d["vm_state"],states_d["lcm_state"]))
        else:
            debug_log_print("in vm state: %s , lcm state %s is not possible to change state" % (states_d["vm_state"],states_d["lcm_state"]))
            raise KypoError("in vm state: %s , lcm state %s is not possible to change state" % (states_d["vm_state"],states_d["lcm_state"]))

        node_d["state"] = wanted_vmstate_after_action[whattodo]
        update_node_db(nodeid, node_d)

    else: #OpenStack
        pass


def connect_nodes_nebula(n1, n2, mac1, mac2):
    if not mac1:
        mac1 = str(MacAddress.from_parts(macprefix=MAC_PREFIX_DEFAULT))
    if not mac2:
        mac2 = str(MacAddress.from_parts(macprefix=MAC_PREFIX_DEFAULT))

    node1_d = get_node_db(n1)
    node1_d["mac_addr"] = mac1
    node2_d = get_node_db(n2)

    check_state_nebula(node1_d["internal_id"],lcmstate="RUNNING", tries=1)
    check_state_nebula(node2_d["internal_id"],lcmstate="RUNNING", tries=1)

    netid = create_vxlan_nebulanet(mac=mac1,size=1)

    net_d = get_network_db(netid)
    try:
        intfid1 = attach_node_to_net(node1_d,netid,waitforcompletion=False)
    except BaseException ,e:
        t, v, tb = sys.exc_info()
        debug_log_print_ext("attach node to net error", t , v, tb),
        delete_net_db(netid)
        execute_cmd("onevnet delete {0}".format(net_d["nebulaid"]))
        raise t, v, tb

    net_d = get_network_db(netid)
    add_addrarr_nebulanet(netid, mac2, 1)

    node2_d = get_node_db(n2)
    node2_d["mac_addr"] = mac2

    try:
        intfid2 = attach_node_to_net(node2_d, netid, waitforcompletion=False)
    except BaseException:
        t, v, tb = sys.exc_info()
        try:
            remove_disconnect_interface(intfid1)
        except:
            pass
        try:
            delete_net_db(netid)
        except:
            pass
        execute_cmd("onevnet delete {0}".format(net_d["nebulaid"]))
        raise t, v, tb

    return { "network": netid , "interface1": intfid1 , "interface2": intfid2}


def create_node(templatename, **kwargs):
    templ_d = get_nodetemplate_db(templname=templatename)
    if templ_d["platform"] == "nebula":
        return create_node_nebula(templ_d["id"], **kwargs)
    else:
        # TODO OpenStack
        pass


def create_node_nebula(templateid,nics=None,tags=None, **kwargs):

    #TODO nics

    ownertag = tdata.ownertag
    if not tags:
        tags = [ownertag]
    if tags is not None and isinstance(tags,basestring):
        tags = set(tags.split(","))
        tags.add(ownertag)

    templ_d = get_nodetemplate_db(templateid)
    debug_log_print(templ_d)

    vmtempl = string.Template(templ_d["template"])

    for k,v in kwargs.iteritems():
        templ_d["defaultvalues"][k] = v

    node_d = { "name": kwargs.get("name",None),
               "state": "PENDING",
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

    out, stderr = execute_cmd("onevm create %s" % (tname))

    if "ID:" != out[:3]:
        delete_node_db(db_id)
        debug_log_print_ext("failed node creation", vmtempl.safe_substitute(templ_d["defaultvalues"]), "onevm create %s" % (tname), out, )
        raise KypoError("Error creating vm")
    # template was ok, delete
    os.unlink(tname)

    internalid = int(out.split()[1])

    ## TODO nasledujici predelat na samostatnou funkci, kvuli pouziti s callbacky
    change_condition = threading.Condition()
    with change_condition:
        inittime = datetime.utcnow()
        cb = NotifyTask(node_ids=[db_id], change_selector=None, towhat=None, howmany=1, notifycondition=change_condition)
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
        raise KypoError("too long wait for scheduling")

    time.sleep(4.5)
    nebulainfo = info_node_nebula(internalid)
    usertemplate = nebulainfo["USER_TEMPLATE"]
    sched_msg = usertemplate.get("SCHED_MESSAGE","")
    if "No host with enough capacity to deploy the VM" in sched_msg:
        debug_log_print_ext("No host with enough capacity to deploy the VM")
        out, stderr = execute_cmd("onevm delete {0}".format(internalid))
        delete_node_db(db_id)
        raise KypoError("too long wait for scheduling; {0}".format(out))

    node_d["name"] = nebulainfo["NAME"]
    node_d["state"] = "ACTIVE"
    node_d["internal_id"] = internalid

    update_node_db(db_id, node_d)

    return db_id



def delete_node(dbid):

    node_d = get_node_db(dbid)

    if node_d["platform"] == "nebula":
        deleted = False
        internalid = node_d["internal_id"]

        nodeinterfaces = get_interfaces_db(netid=None, nodeid=dbid)

        if internalid: # node mozna nikdy nebyla vyvorena (i kdyz to by se nemelo stat)
            out, stderr = execute_cmd("onevm delete {0}".format(internalid))
            if out and not "[VirtualMachineAction] Error getting virtual machine" in out:
                raise KypoError(out)

        delete_node_db(dbid)
        for intf in nodeinterfaces:
            try:
                decrease_net_use_db(intf["net_id"])
            except psycopg2.IntegrityError: #to by snad nemelo nastat, ale kdyz uz je smazane VM
                pass

    else:
        pass
    return True



def add_addrarr_nebulanet(netid, mac, size):

    net_d = get_network_db(netid)

    internalid = net_d["nebulaid"]

    out, stderr = execute_cmd("onevnet addar {0} --mac {1} --size {2}".format(internalid, mac, size))

    if out:
        debug_log_print_ext("address range wasn't added to net {0}: ".format(internalid) , out)
        KypoError("address range wasn't added to net")
    increase_net_size_db(netid, howmuch=size)


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
        raise NoSuchObjectException("node with nebula id %d doesn't exist" % nebulaid)
    return node

def info_nebulanet(nebulaid):
    nets_info_lock.acquire()
    net = copy.deepcopy(NODES_INFO.get(nebulaid))
    nets_info_lock.release()

    if not net:
        raise NoSuchObjectException("net with net id %d doesn't exist" % nebulaid)
    return net


def recursive_element_list(elem):
    children = list(elem)
    if children:
        subs = []
        for child in children:
            subs.append(recursive_element_list(child))

        subs_d = {}
        for k,v in subs:
            prev_val = subs_d.get(k,[])
            prev_val.append(v)
            subs_d[k] = prev_val

        for k in subs_d.keys():
            if len(subs_d[k]) == 1:
                subs_d[k] = subs_d[k][0]

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



def list_vxlan_nebulanets():
    vnets = list_nebulanets_xml()

    vxvnets = {}
    for i in vnets.keys():
        if "kypo vxlan-" not in vnets[i]["NAME"]:
            continue

        vxvnets[i] = vnets[i]
    return vxvnets

def list_public_nebulanets():
    nets = list_nebulanets_xml()
    pubnets = {}

    for nk in nets.keys():
        if nets[nk]["NAME"].startswith(PUBLIC_NET_NAME_TEMPL[:-3]):
            continue
        pubnets[nk] = nets[nk]
    return pubnets


def get_node_state_nebula(nebulaid):

    ni = info_node_nebula(nebulaid)
    vm_state = ni["STATE"]
    lcm_state = ni["LCM_STATE"]
    value = {"vm_state": NUM2VMSTATE[vm_state], "lcm_state": NUM2LCMSTATE[lcm_state],
             "STATE": NUM2VMSTATE[vm_state], "LCM_STATE": NUM2LCMSTATE[lcm_state]}

    return value

def check_state_nebula(nebulaid, vmstate=None, lcmstate=None, tries=1):
    realvmstate = None
    reallcmstate = None
    while tries >= 1:
        states = get_node_state_nebula(nebulaid)
        if vmstate:
            realvmstate = states["vm_state"]
        if lcmstate:
            reallcmstate = states["lcm_state"]

        if vmstate == realvmstate and lcmstate==reallcmstate:
            return True

        if tries == 1:
            raise WrongStateForActionException("attempted action isn't possible due to node being in wrong state")
        tries = tries - 1
        time.sleep(4.2)
    return True



def get_node_state(nodeid, selector=None):
    db_node_info = get_node_db(nodeid)

    platform = db_node_info["platform"]

    if platform == "nebula":
        value = get_node_state_nebula(db_node_info["internal_id"])
        state = value["vm_state"]
        if db_node_info["state"] != state:
            db_node_info["state"] = state
            update_node_db(nodeid, db_node_info)

    else:
        #OpenStack
        pass

    if selector:
        return value[selector]

    return value

def list_nebula_images():
    try:
        out, stderr = execute_cmd_e("oneimage list -x")
        tree = ET.fromstring(out)

        #root = tree.getroot()
        imgs = {}
        for img in tree:
            k,v = recursive_element_list(img)
            id = v['ID']
            imgs[id] = v
    except RuntimeError as e:
        debug_log_print(e)
        return {}
    return imgs



from flask import Flask, url_for, jsonify, make_response, request
from flask.ext.httpauth import HTTPBasicAuth
auth = HTTPBasicAuth()

app = Flask(__name__)

@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({'error': 'Not found'}), 404)

@auth.verify_password
def verify_password(username, password):
    tdata.DB_CON = open_db2()
    with tdata.DB_CON:
        res_d = get_user(username)
        if not res_d:
            return False

        tdata.username = username
        tdata.isadmin = res_d["isadmin"]
        tdata.userid = res_d["id"]
        tdata.extended_error_log = ""
        tdata.ownertag = "owner:{0}".format(username)

        derivedkey = hashlib.pbkdf2_hmac('sha256', password, res_d["salt"], 100000)
        hexalified = binascii.hexlify(derivedkey)

    return res_d["password"] == hexalified

@auth.error_handler
def unauthorized():
    return make_response(jsonify({'error': 'Unauthorized access'}), 403)


@app.route('/')
def api_root():
    return 'Kypo api\npožádejte o vytvoření uživatelského účtu'

@app.route('/api/v1.0/tags', methods=['GET'])
@auth.login_required
def api_tags_list():
    status = "success"
    answ = {"data": {}}

    try:
        data = get_tags()
        answ["data"]["tags"] = data
    except BaseException as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))

@app.route('/api/v1.0/tags', methods=['POST'])
@auth.login_required
def api_tags_add():
    status = "success"
    answ = {"data": {}}
    added = []

    try:
        reqdata = json.loads(request.data)
        tags = reqdata["tags"]
        if isinstance(tags, basestring):
            create_tag(tags)
            added.append(tags)
        else:
            for t in tags:
                try:
                    create_tag(t)
                    added.append(t)
                except DuplicateNameException:
                    pass
    except KypoError as e:
        status = "failure"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)

    answ["data"]["tags"] = added
    answ["status"] = status

    return make_response(jsonify(answ))

@app.route('/api/v1.0/images', methods=['GET'])
@auth.login_required
def api_images_list():
    status = "success"
    answ = {"data": {}}

    try:
        data = list_nebula_images()
        answ["data"]["images"] = data
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))

@app.route('/api/v1.0/templates', methods=['GET'])
@auth.login_required
def api_templates_list():
    status = "success"
    answ = {"data": {}}

    try:
        data = get_templates_db(request.args.get("user", None), extractdefaults=False)
        answ["data"]["templates"] = data
    except KypoError as e:
        status = "failure"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log
    except BaseException as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))

@app.route('/api/v1.0/templates', methods=['POST'])
@auth.login_required
def api_templates_add():
    status = "success"
    answ = {"data": {}}
    debug_log_print(request.data)

    try:
        reqdata = json.loads(request.data)
        templstring = reqdata.pop("template")
        name = reqdata.pop("name")
        dbid = add_nodetemplate_db(templstring,name,**reqdata)
        data = {"name": name, "id": dbid}
        answ["data"]["template"] = data
    except KypoError as e:
        status = "failure"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)

    answ["status"] = status

    return make_response(jsonify(answ))

@app.route('/api/v1.0/templates/<selector>', methods=['GET'])
@auth.login_required
def api_template_get(selector):
    status = "success"
    answ = {"data": {}}

    templid = None
    templname = None
    try:
        templid = int(selector)
    except ValueError:
        templname = selector

    try:
        data = get_nodetemplate_db(templid=templid, templname=templname, extractdefaults=False)
        answ["data"]["template"] = data
    except KypoError as e:
        status = "failure"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log
    except BaseException as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))



@app.route('/api/v1.0/nodes', methods=['GET'])
@auth.login_required
def api_nodes_list():
    status = "success"
    answ = {"data": {}}

    try:
        data = get_nodes_db_and_internal()
        answ["data"]["nodes"] = data
    except BaseException as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes/<int:nodeid>', methods=['GET'])
@auth.login_required
def api_node_get(nodeid):
    status = "success"
    answ = {"data": {}}
    try:
        get_node_state(nodeid)
        data = get_node_db_and_internal(nodeid)
        answ["data"]["node"] = data
    except PrivilegeException as e:
        status = "failure"
        debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = "you are neither owner nor admin"
    except NoSuchObjectException as e:
        status = "failure"
        debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = "no such node id exists"
    except BaseException as e:
        status = "error"
        debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes', methods=['POST'])
@auth.login_required
def api_node_create():
    status = "success"
    answ = {"data": {}}
    # debug_log_print(request.data)

    try:
        reqdata = json.loads(request.data)
        templname = reqdata.pop("templatename")
        dbid = create_node(templname,**reqdata)
        answ["data"]["node"] = { dbid: get_node_db_and_internal(dbid) }
    except KypoError as e:
        status = "failure"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes/<int:nodeid>', methods=['DELETE'])
@auth.login_required
def api_node_delete(nodeid):
    status = "success"
    answ = {"data": {}}
    # debug_log_print(request.data)

    try:
        delete_node(nodeid)
        answ["data"]["deleted"] = True
    except KypoError as e:
        status = "failure"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))





@app.route('/api/v1.0/nets', methods=['GET'])
@auth.login_required
def api_nets_list():
    status = "success"
    answ = {"data": {}}

    try:
        data = get_networks_db_and_internal()
        answ["data"]["nets"] = data
    except BaseException as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nets/<int:netid>', methods=['GET'])
@auth.login_required
def api_net_get(netid):
    status = "success"
    answ = {"data": {}}
    try:
        get_node_state(netid)
        data = get_network_db_and_internal(netid)
        answ["data"]["net"] = data
    except PrivilegeException as e:
        status = "failure"
        debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = "you are neither owner nor admin"
    except NoSuchObjectException as e:
        status = "failure"
        debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = "no such net id exists"
    except BaseException as e:
        status = "error"
        debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))






if __name__ == '__main__':
    tdata.DB_CON = open_db2()
    with tdata.DB_CON:

        tdata.username = None

        poller = InfoPoller()
        poller.setDaemon(daemonic=True)
        debug_log_print("start poller")
        poller.start()
        debug_log_print("started poller")
        time.sleep(1)
        if len(sys.argv) >=2 and sys.argv[1] == "server":

            callbackdispatcher = CallbackSender()
            callbackdispatcher.setDaemon(daemonic=True)
            debug_log_print("start callback dispatcher")
            callbackdispatcher.start()
            debug_log_print("started callback dispatcher ")

            app.run(threaded=True)
            # app.run()


        else:
            # add_user("tester", "tester", isadmin=True)
            res_d = get_user("tester")
            if not res_d:
                raise PrivilegeException("first create user")

            tdata.username = res_d["name"]
            tdata.isadmin = res_d["isadmin"]
            tdata.extended_error_log = ""
            tdata.ownertag = "owner:{0}".format(res_d["name"])


            tdata.username = "tester"
            tdata.extended_error_log = ""


            nodetmpl = '''
    CPU=$cpu
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

            default_node_values = dict( image_id = 61,
                            vnc_passwd = "d3f4u1t_vNc.p4s5W0rD!",
                            cluster = CLUSTER_NAME,
                            cpu = 1,
                            vcpu = 1,
                            memory = 512,
                            )

            # add_nodetemplate_db(nodetmpl,"test_vm4", defaultvalues=default_node_values)
            #
            # nodeid = create_node("test_vm4")
            # debug_log_print("node created:", nodeid)
            # nodeid = create_node("test_vm4")
            # debug_log_print("node created:", nodeid)


            # debug_log_print("Nodes DB:", get_nodes_db(tags=["LMN","user:jirka"]))

            # add_tag_node(["ZZZZZ"], 1)
            # add_tag_node(["LMN","user:jirka"], 2)
            # add_tag_node(["SMN"], 1)
            # add_tag_node(["LMN","user:donald"], 3)
            # add_tag_node(["SMN"], 4)

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
            debug_print("more:", get_networks_db_and_internal())
            # debug_print("vxids", get_used_vxids_db())

            # debug_log_print(connect_nodes_nebula(1,2,None,None))

            # add_new_networks_db()
            # debug_log_print(list_vxlan_nebulanets()[188])
            # debug_log_print("Nets DB:", get_network_db(177))
            # debug_log_print(get_tags_node(3))





            #debug_log_print(get_nodetemplate_db(1))
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
        #pprint.pprint(list_templates_nebula())

