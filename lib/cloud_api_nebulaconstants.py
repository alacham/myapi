
ADDRESS_RANGE='AR=[TYPE="ETHER", MAC="{0}", SIZE="{1}"]'

NICLINE='NIC=[MODEL=virtio, NETWORK_ID=$netid#NUMBER#, NETWORK_UNAME=$netowner]'

VM_STATE=["INIT", "PENDING", "HOLD", "ACTIVE", "STOPPED", "SUSPENDED", "DONE", "FAILED", "POWEROFF", "UNDEPLOYED"]
SHORT_VM_STATES={
            "INIT"      : "init",
            "PENDING"   : "pend",
            "HOLD"      : "hold",
            "ACTIVE"    : "actv",
            "STOPPED"   : "stop",
            "SUSPENDED" : "susp",
            "DONE"      : "done",
            "FAILED"    : "fail",
            "POWEROFF"  : "poff",
            "UNDEPLOYED": "unde"
        }

VMSTATE2NUM = dict(map(lambda a: (a, VM_STATE.index(a)), VM_STATE))
NUM2VMSTATE = dict(map(lambda a: (VM_STATE.index(a), a), VM_STATE))
LCM_STATE=["LCM_INIT","PROLOG","BOOT","RUNNING","MIGRATE","SAVE_STOP","SAVE_SUSPEND",
           "SAVE_MIGRATE","PROLOG_MIGRATE","PROLOG_RESUME","EPILOG_STOP","EPILOG","SHUTDOWN",
           "CANCEL","FAILURE","CLEANUP_RESUBMIT","UNKNOWN","HOTPLUG","SHUTDOWN_POWEROFF",
           "BOOT_UNKNOWN","BOOT_POWEROFF","BOOT_SUSPENDED","BOOT_STOPPED","CLEANUP_DELETE",
           "HOTPLUG_SNAPSHOT","HOTPLUG_NIC","HOTPLUG_SAVEAS","HOTPLUG_SAVEAS_POWEROFF",
           "HOTPLUG_SAVEAS_SUSPENDED","SHUTDOWN_UNDEPLOY","EPILOG_UNDEPLOY","PROLOG_UNDEPLOY",
           "BOOT_UNDEPLOY","HOTPLUG_PROLOG_POWEROFF","HOTPLUG_EPILOG_POWEROFF","BOOT_MIGRATE",
           "BOOT_FAILURE","BOOT_MIGRATE_FAILURE","PROLOG_MIGRATE_FAILURE","PROLOG_FAILURE",
           "EPILOG_FAILURE","EPILOG_STOP_FAILURE","EPILOG_UNDEPLOY_FAILURE",
           "PROLOG_MIGRATE_POWEROFF","PROLOG_MIGRATE_POWEROFF_FAILURE","PROLOG_MIGRATE_SUSPEND",
           "PROLOG_MIGRATE_SUSPEND_FAILURE","BOOT_UNDEPLOY_FAILURE","BOOT_STOPPED_FAILURE",
           "PROLOG_RESUME_FAILURE","PROLOG_UNDEPLOY_FAILURE","DISK_SNAPSHOT_POWEROFF",
           "DISK_SNAPSHOT_REVERT_POWEROFF","DISK_SNAPSHOT_DELETE_POWEROFF",
           "DISK_SNAPSHOT_SUSPENDED","DISK_SNAPSHOT_REVERT_SUSPENDED","DISK_SNAPSHOT_DELETE_SUSPENDED",
           "DISK_SNAPSHOT","DISK_SNAPSHOT_REVERT","DISK_SNAPSHOT_DELETE"]
SHORT_LCM_STATES={
            "PROLOG"            : "prol",
            "BOOT"              : "boot",
            "RUNNING"           : "runn",
            "MIGRATE"           : "migr",
            "SAVE_STOP"         : "save",
            "SAVE_SUSPEND"      : "save",
            "SAVE_MIGRATE"      : "save",
            "PROLOG_MIGRATE"    : "migr",
            "PROLOG_RESUME"     : "prol",
            "EPILOG_STOP"       : "epil",
            "EPILOG"            : "epil",
            "SHUTDOWN"          : "shut",
            "CANCEL"            : "shut",
            "FAILURE"           : "fail",
            "CLEANUP_RESUBMIT"  : "clea",
            "UNKNOWN"           : "unkn",
            "HOTPLUG"           : "hotp",
            "SHUTDOWN_POWEROFF" : "shut",
            "BOOT_UNKNOWN"      : "boot",
            "BOOT_POWEROFF"     : "boot",
            "BOOT_SUSPENDED"    : "boot",
            "BOOT_STOPPED"      : "boot",
            "CLEANUP_DELETE"    : "clea",
            "HOTPLUG_SNAPSHOT"  : "snap",
            "HOTPLUG_NIC"       : "hotp",
            "HOTPLUG_SAVEAS"           : "hotp",
            "HOTPLUG_SAVEAS_POWEROFF"  : "hotp",
            "HOTPLUG_SAVEAS_SUSPENDED" : "hotp",
            "SHUTDOWN_UNDEPLOY" : "shut",
            "EPILOG_UNDEPLOY"   : "epil",
            "PROLOG_UNDEPLOY"   : "prol",
            "BOOT_UNDEPLOY"     : "boot",
            "HOTPLUG_PROLOG_POWEROFF"   : "hotp",
            "HOTPLUG_EPILOG_POWEROFF"   : "hotp",
            "BOOT_MIGRATE"              : "boot",
            "BOOT_FAILURE"              : "fail",
            "BOOT_MIGRATE_FAILURE"      : "fail",
            "PROLOG_MIGRATE_FAILURE"    : "fail",
            "PROLOG_FAILURE"            : "fail",
            "EPILOG_FAILURE"            : "fail",
            "EPILOG_STOP_FAILURE"       : "fail",
            "EPILOG_UNDEPLOY_FAILURE"   : "fail",
            "PROLOG_MIGRATE_POWEROFF"   : "migr",
            "PROLOG_MIGRATE_POWEROFF_FAILURE"   : "fail",
            "PROLOG_MIGRATE_SUSPEND"            : "migr",
            "PROLOG_MIGRATE_SUSPEND_FAILURE"    : "fail",
            "BOOT_UNDEPLOY_FAILURE"     : "fail",
            "BOOT_STOPPED_FAILURE"      : "fail",
            "PROLOG_RESUME_FAILURE"     : "fail",
            "PROLOG_UNDEPLOY_FAILURE"   : "fail",
            "DISK_SNAPSHOT_POWEROFF"        : "snap",
            "DISK_SNAPSHOT_REVERT_POWEROFF" : "snap",
            "DISK_SNAPSHOT_DELETE_POWEROFF" : "snap",
            "DISK_SNAPSHOT_SUSPENDED"       : "snap",
            "DISK_SNAPSHOT_REVERT_SUSPENDED": "snap",
            "DISK_SNAPSHOT_DELETE_SUSPENDED": "snap",
            "DISK_SNAPSHOT"        : "snap",
            "DISK_SNAPSHOT_REVERT" : "snap",
            "DISK_SNAPSHOT_DELETE" : "snap"
        }

LCMSTATE2NUM = dict(map(lambda a: (a, LCM_STATE.index(a)), LCM_STATE))
NUM2LCMSTATE = dict(map(lambda a: (LCM_STATE.index(a), a), LCM_STATE))


