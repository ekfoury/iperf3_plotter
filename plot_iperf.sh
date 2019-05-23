#!/bin/bash


if [ $# -ne 1 ]; then
	echo "***************************************"
	echo "Usage: $0 <iperf_json_file>"
	echo "***************************************"
fi

preprocessor.sh $1 .

if [ $? -ne 0 ]; then
	exit 1
fi

cd results
gnuplot /usr/bin/*.plt 2> /dev/null

