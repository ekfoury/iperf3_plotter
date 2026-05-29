#!/bin/bash

#Verify number of parameters is 2
if [ $# -ne 2 ]; then
        echo "Usage: $0 <iperf_json_input> <output_directory>"
        exit 1
fi

#Check if passed parameter is a file
if [ ! -f $1 ]; then
        echo "Error: $1 is not a file. Quitting..."
        exit 2
fi

#Check if passed paramter is a valid JSON
jq empty < $1 >> /dev/null 2>&1
if [ $? -ne 0 ]; then
	echo "Error: $1 is not a valid JSON file. Quitting..."
	exit 3
fi

# Convert iperf's JSON output to CSV
res=`cat $1 | jq -r '.intervals[].streams[] | [.socket, .start, .end, .seconds, .bytes, .bits_per_second, .retransmits, .snd_cwnd, .rtt, .rttvar, .pmtu, .omitted] | @csv'`

mkdir -p $2

# Insert new lines on each record
# Sort the file (by default, will be sorted by socket, or by client)
# Redirect the output to a file in the specified directory named iperf.csv
echo $res | sed 's/ /\n/g' | sort > $2/"iperf.csv"

# Count the number of iperf client flows
num_flows=`jq '.end.sum_sent.seconds' $1 | cut -d. -f1` 

# Create a directory 'results' to store all flows data
mkdir -p $2/results
rm -rf $2/results/*

split -l $num_flows --numeric=1 --additional-suffix=".dat" $2/iperf.csv flow_
mv flow_* $2/results 2> /dev/null
curr=`pwd`
cd $2/results
for FILE in `ls`; do mv $FILE `echo $FILE | sed -e 's:^\(flow_\)0*::'` 2> /dev/null; done
cd $curr

for file in $2/results/*.dat; do
	awk -F, '{print ($1,int($2),int($3),($5/1024)/1024,$6/1024/1024,$7,$8/1024,$9,$10,$11,$12)}' $file | sort -n -k 2 > tmp
	mv tmp $file 2> /dev/null
done

