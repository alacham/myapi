#!/bin/bash

MYIP=`hostname  -I | cut -f1 -d' '`

IPS="147.251.54.221\n147.251.54.222"

OTHERIPS=`echo -e $IPS | grep -v $MYIP`


for vxintf in `ip l | grep -E "^.*br-inet\..*$" | sed 's/^.*\(br-inet\.[0-9]*\).*/\1/'`
do
	for remip in $OTHERIPS
	do
		bridge fdb append 00:00:00:00:00:00 dev $vxintf dst $remip via br-inet
	done
done

# * * * * * /root/bin/vxlan-multi-setter.sh
