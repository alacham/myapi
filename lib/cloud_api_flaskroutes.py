# -*- coding: utf-8 -*-

import hashlib
import json
import sys
import time

from flask import Flask, jsonify, make_response, request
from flask.ext.httpauth import HTTPBasicAuth

import cloud_api_main

auth = HTTPBasicAuth()

app = Flask(__name__)


@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({"status": "fail", 'message': 'Not found (no handler for this path/action)'}), 404)


@auth.verify_password
def verify_password(username, password):
    cloud_api_main.tdata.DB_CON = cloud_api_main.open_db2()
    with cloud_api_main.tdata.DB_CON:
        res_d = cloud_api_main.get_user(username)
        if not res_d:
            return False

        cloud_api_main.tdata.username = username
        cloud_api_main.tdata.isadmin = res_d["isadmin"]
        cloud_api_main.tdata.userid = res_d["id"]
        cloud_api_main.tdata.extended_error_log = ""
        cloud_api_main.tdata.ownertag = "owner:{0}".format(username)

        # derivedkey = hashlib.pbkdf2_hmac('sha256', password, res_d["salt"], 100000)
        # hexalified = binascii.hexlify(derivedkey)
        hexalified = hashlib.sha512(password + res_d["salt"]).hexdigest()

    return res_d["password"] == hexalified


@auth.error_handler
def unauthorized():
    return make_response(jsonify({"status": "fail", 'message': 'Unauthorized access'}), 403)


@app.route('/')
def api_root():
    print request.args.get("asdf")
    return 'Kypo api\npožádejte o vytvoření uživatelského účtu'


@app.route('/deletions', methods=['GET'])
def api_deletions():
    cloud_api_main.tdata.DB_CON = cloud_api_main.open_db2()
    cloud_api_main.tdata.isadmin = True
    everything = ""
    vmdel = "onevm delete {0} \n"
    vnetdel = "onevnet delete {0} \n"

    try:
        for i in cloud_api_main.get_nodes_db().itervalues():
            everything += vmdel.format(i["internal_id"])

        for i in cloud_api_main.get_networks_db().itervalues():
            everything += vnetdel.format(i["nebulaid"])
    except Exception as e:
        cloud_api_main.debug_log_print("Error:", repr(e))

    return everything


@app.route('/api/v1.0/tags', methods=['GET'])
@auth.login_required
def api_tags_list():
    status = "success"
    answ = {"data": {}}

    try:
        data = cloud_api_main.get_tags()
        answ["data"]["tags"] = data
    except BaseException as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

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
            cloud_api_main.create_tag(tags)
            added.append(tags)
        else:
            for t in tags:
                try:
                    cloud_api_main.create_tag(t)
                    added.append(t)
                except cloud_api_main.DuplicateNameException:
                    pass
    except cloud_api_main.GeneralAPIError as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)

    answ["data"]["tags"] = added
    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nebulaimages', methods=['GET'])
@auth.login_required
def api_images_list():
    status = "success"
    answ = {"data": {}}

    try:
        data = cloud_api_main.list_nebula_images()
        answ["data"]["images"] = data
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/templates', methods=['GET'])
@auth.login_required
def api_templates_list():
    status = "success"
    answ = {"data": {}}

    try:
        data = cloud_api_main.get_templates_db(request.args.get("user", None), extractdefaults=False)
        answ["data"]["templates"] = data
    except cloud_api_main.GeneralAPIError as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log
    except BaseException as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/templates', methods=['POST'])
@auth.login_required
def api_templates_add():
    status = "success"
    answ = {"data": {}}

    try:
        cloud_api_main.debug_log_print_ext("attempting to add template from request:", request.data)
        reqdata = json.loads(request.data)
        templstring = reqdata.pop("template")
        name = reqdata.pop("name")
        dbid = cloud_api_main.add_nodetemplate_db(templstring, name, **reqdata)
        data = {"name": name, "id": dbid}
        answ["data"]["template"] = data
    except cloud_api_main.GeneralAPIError as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/templates/<selector>', \
           methods=['GET'])
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
        data = cloud_api_main.get_nodetemplate_db(templid=templid, templname=templname, extractdefaults=False)
        answ["data"]["template"] = data
    except cloud_api_main.GeneralAPIError as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log
    except BaseException as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes', methods=['GET'])
@auth.login_required
def api_nodes_list():
    status = "success"
    answ = {"data": {}}

    try:
        data = cloud_api_main.get_nodes_db_for_output()
        answ["data"]["nodes"] = data.values()
    except BaseException as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes/<int:nodeid>', methods=['GET'])
@auth.login_required
def api_node_get(nodeid):
    status = "success"
    answ = {"data": {}}
    try:
        data = cloud_api_main.get_node_db_for_output(nodeid)
        answ["data"]["node"] = data
        answ["data"]["node"]["tags"] = cloud_api_main.get_tags_node(nodeid)
    except cloud_api_main.PrivilegeException as e:
        status = "fail"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + " you are neither owner nor admin of this node"
    except cloud_api_main.NoSuchObjectException as e:
        status = "fail"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + " no such node id exists"
    except BaseException as e:
        status = "error"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes/<int:nodeid>/status', methods=['GET'])
@auth.login_required
def api_node_get_status(nodeid):
    status = "success"
    answ = {"data": {}}
    try:
        data = cloud_api_main.get_node_state(nodeid)
        answ["data"] = data
    except (cloud_api_main.PrivilegeException, cloud_api_main.NoSuchObjectException) as e:
        status = "fail"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.get_user_problem_msg()
    except BaseException as e:
        status = "error"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))

@app.route('/api/v1.0/nodes/<int:nodeid>/status', methods=['PUT'])
@auth.login_required
def api_node_set_status(nodeid):
    status = "success"
    answ = {"data": {}}
    try:
        data = cloud_api_main.get_node_state(nodeid)
        answ["data"] = data
    except cloud_api_main.PrivilegeException as e:
        status = "fail"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + "you are neither owner nor admin of this node"
    except cloud_api_main.NoSuchObjectException as e:
        status = "fail"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + "no such node id exists"
    except BaseException as e:
        status = "error"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))



@app.route('/api/v1.0/nodes/<int:nodeid>/vncinfo', methods=['GET'])
@auth.login_required
def api_node_get_vncinfo(nodeid):
    status = "success"
    answ = {"data": {}}
    try:
        nodeinfo = cloud_api_main.get_node_db_for_output(nodeid)
        if nodeinfo["state"] == "UNKNOWN":
            raise cloud_api_main.NoSuchObjectException("underlying nebula node probably doesn't exist ")
        if cloud_api_main.get_node_state(nodeid, selector="lcm_state") != "RUNNING":
            raise cloud_api_main.WrongStateForActionException("that node isn't running")
        internal = cloud_api_main.info_node_nebula(nodeinfo["internal_id"])
        info = {"host": internal["HISTORY_RECORDS"]["HISTORY"]["HOSTNAME"],
                "port": internal["TEMPLATE"]["GRAPHICS"]["PORT"],
                "password": internal["TEMPLATE"]["GRAPHICS"]["PASSWD"]}

        answ["data"]["vncinfo"] = info
    except cloud_api_main.PrivilegeException as e:
        status = "fail"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + "you are neither owner nor admin of this node"
    except cloud_api_main.NoSuchObjectException as e:
        status = "fail"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + "no such node id exists"
    except BaseException as e:
        status = "error"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes/<int:nodeid>', methods=['DELETE'])
@auth.login_required
def api_node_delete(nodeid):
    status = "success"
    answ = {"data": {}}
    # debug_log_print(request.data)

    try:
        cloud_api_main.delete_node(nodeid)
        answ["data"]["deleted"] = True
    except cloud_api_main.GeneralAPIError as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes', methods=['POST'])
@auth.login_required
def api_node_create():
    status = "success"
    answ = {"data": {}}
    cloud_api_main.debug_log_print("Create node", request.data)

    try:
        reqdata = json.loads(request.data)
        templname = reqdata.pop("templatename")
        dbid = cloud_api_main.create_node(templname, **reqdata)
        answ["data"]["node"] = cloud_api_main.get_node_db_for_output(dbid)
    except cloud_api_main.GeneralAPIError as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nets', methods=['GET'])
@auth.login_required
def api_nets_list():
    status = "success"
    answ = {"data": {}}

    try:
        data = cloud_api_main.get_networks_db_for_output()
        answ["data"]["nets"] = data.values()
    except BaseException as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nets/<int:netid>', methods=['DELETE'])
@auth.login_required
def api_net_delete(netid):
    status = "success"
    answ = {"data": {}}
    try:
        cloud_api_main.remove_network(netid)
        answ["data"]["deleted"] = netid
    except cloud_api_main.GeneralAPIError as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nets', methods=['POST'])
@auth.login_required
def api_net_create_link():
    status = "success"
    answ = {"data": {}}
    # debug_log_print(request.data)

    try:
        cloud_api_main.debug_log_print_ext("attmpting to load from json", request.data)
        reqdata = cloud_api_main.json.loads(request.data)

        n1 = reqdata.pop("node1")
        n2 = reqdata.pop("node2")

        data = cloud_api_main.connect_nodes_nebula(n1, n2, **reqdata)

        answ["data"]["connection"] = data
    except cloud_api_main.GeneralAPIError as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nets/<int:netid>', methods=['GET'])
@auth.login_required
def api_net_get(netid):
    status = "success"
    answ = {"data": {}}
    try:
        data = cloud_api_main.get_network_db_for_output(netid)
        answ["data"]["net"] = data
    except cloud_api_main.PrivilegeException as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + " you are neither owner nor admin"
    except cloud_api_main.NoSuchObjectException as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + "no such net id exists"
    except BaseException as e:
        status = "error"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nets/<int:netid>/interfaces', methods=['GET'])
@auth.login_required
def api_net_interfaces_get(netid):
    status = "success"
    answ = {"data": {}}
    try:
        cloud_api_main.check_user_privilege_net(netid)
        data = cloud_api_main.get_interfaces_db(netid=netid)
        answ["data"]["interfaces"] = data.values()
    except cloud_api_main.PrivilegeException as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + " you are neither owner nor admin"
    except cloud_api_main.NoSuchObjectException as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + "no such net id exists"
    except BaseException as e:
        status = "error"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes/<int:nodeid>/interfaces', methods=['GET'])
@auth.login_required
def api_node_interfaces_get(nodeid):
    status = "success"
    answ = {"data": {}}
    try:
        cloud_api_main.check_user_privilege_node(nodeid)

        data = cloud_api_main.get_interfaces_db(nodeid=nodeid)
        answ["data"]["interfaces"] = data.values()
    except cloud_api_main.PrivilegeException as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + " you are neither owner nor admin"
    except cloud_api_main.NoSuchObjectException as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log + "no such node id exists"
    except BaseException as e:
        status = "error"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/interfaces/<int:intfid>', methods=['GET'])
@auth.login_required
def api_interface_get(intfid):
    status = "success"
    answ = {"data": {}}
    try:
        data = cloud_api_main.get_interface_db(intfid)
        answ["data"]["interface"] = data
    except (cloud_api_main.PrivilegeException, cloud_api_main.NoSuchObjectException) as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.get_user_problem_msg()
    except BaseException as e:
        status = "error"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.tdata.extended_error_log

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/interfaces/<int:intfid>', methods=['DELETE'])
@auth.login_required
def api_interface_delete(intfid):
    status = "success"
    answ = {"data": {}}
    try:
        # TODO odstranit i addr range?
        cloud_api_main.remove_disconnect_interface(intfid)

        answ["data"]["deleted"] = True
    except (cloud_api_main.PrivilegeException, cloud_api_main.NoSuchObjectException) as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.get_user_problem_msg()
    except BaseException as e:
        status = "error"
        cloud_api_main.debug_log_print(e)
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.get_user_problem_msg()

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes/<int:nodeid>/tags', methods=['POST'])
@auth.login_required
def api_node_tags_add(nodeid):
    status = "success"
    answ = {"data": {}}
    cloud_api_main.debug_log_print("Add tags", request.data)

    try:
        cloud_api_main.check_user_privilege_node(nodeid)
        added = []
        reqdata = json.loads(request.data)
        tags = reqdata["tags"]
        alltags = cloud_api_main.get_tags()
        if isinstance(tags, basestring):
            tags = [tags]
        tags = set(tags)
        for t in tags:
            if t not in alltags:
                cloud_api_main.create_tag(t)
            cloud_api_main.add_tag_node(t, nodeid)
        answ["data"]["tags"] = list(tags)
    except (cloud_api_main.PrivilegeException, cloud_api_main.NoSuchObjectException) as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.get_user_problem_msg()
    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.get_user_problem_msg()

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes/<int:nodeid>/tags', methods=['PUT'])
@auth.login_required
def api_node_tags_change(nodeid):
    status = "success"
    answ = {"data": {}}
    cloud_api_main.debug_log_print("Change tags", request.data)

    try:
        cloud_api_main.check_user_privilege_node(nodeid)

        reqdata = json.loads(request.data)
        tags = reqdata["tags"]
        if isinstance(tags, basestring):
            tags = [tags]
        tags = set(tags)
        tags.add(cloud_api_main.tdata.ownertag)

        alltags = cloud_api_main.get_tags()
        currtags = set(cloud_api_main.get_tags_node(nodeid))

        to_remove = currtags.difference(tags).intersection(alltags)
        to_add = tags.difference(currtags)

        for t in to_add:
            if t not in alltags:
                cloud_api_main.create_tag(t)
            cloud_api_main.add_tag_node(t, nodeid)
        cloud_api_main.remove_tag_node(to_remove, nodeid)

        answ["data"]["tags"] = cloud_api_main.get_tags_node(nodeid)
    except (cloud_api_main.PrivilegeException, cloud_api_main.NoSuchObjectException) as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.get_user_problem_msg()

    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.get_user_problem_msg()

    answ["status"] = status

    return make_response(jsonify(answ))


@app.route('/api/v1.0/nodes/<int:nodeid>/tags/<tag>', methods=['DELETE'])
@auth.login_required
def api_node_tags_delete(nodeid,tag):
    status = "success"
    answ = {"data": {}}
    cloud_api_main.debug_log_print("Change tags", request.data)

    try:
        cloud_api_main.check_user_privilege_node(nodeid)

        if tag == cloud_api_main.tdata.usertag:
            cloud_api_main.add_to_user_problem_msg("you can't remove your own usertag")
            raise cloud_api_main.PrivilegeException("can't remove this tag")

        tags = set((tag,))

        currtags = set(cloud_api_main.get_tags_node(nodeid))

        to_remove = tags.intersection(currtags)

        cloud_api_main.remove_tag_node(to_remove, nodeid)

        answ["data"]["deleted"] = True
    except (cloud_api_main.PrivilegeException, cloud_api_main.NoSuchObjectException) as e:
        status = "fail"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.get_user_problem_msg()

    except Exception as e:
        status = "error"
        answ["message"] = repr(e)
        answ["data"]["description"] = cloud_api_main.get_user_problem_msg()

    answ["status"] = status

    return make_response(jsonify(answ))





if __name__ == '__main__':
    poller = cloud_api_main.InfoPoller()
    poller.setDaemon(daemonic=True)
    cloud_api_main.debug_log_print("start poller")
    poller.start()
    cloud_api_main.debug_log_print("started poller")

    checker = cloud_api_main.CallbackChecker()
    checker.setDaemon(daemonic=True)
    checker.start()

    time.sleep(1)
    cloud_api_main.tdata.DB_CON = cloud_api_main.open_db2()
    with cloud_api_main.tdata.DB_CON:

        if len(sys.argv) >= 2 and sys.argv[1] == "server":

            callbackdispatcher = cloud_api_main.CallbackDispatcher()
            callbackdispatcher.setDaemon(daemonic=True)
            cloud_api_main.debug_log_print("start callback dispatcher")
            callbackdispatcher.start()
            cloud_api_main.debug_log_print("started callback dispatcher ")

            app.run('0.0.0.0', threaded=True)