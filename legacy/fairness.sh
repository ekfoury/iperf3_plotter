#!/bin/bash

# This script reads either a single JSON file exported from iPerf3 that has multiple parallel streams,
# or multiple JSON files exported from iPerf3 BUT each file has 1 flow,
# and calculate the fairness index according to Raj Jain's formula:
# Fairness index = [(sum xi)**2] / {n * sum[(xi)**2]}


echo "*****************************************************************"
echo "This script calculates the fairness index among parallels streams"
echo "or among several JSON files exported from iPerf3, 1 flow per each"
echo "-----------------------------------------------------------------"
echo "                         SUM(xi)^2"
echo "F(x1, x2, ... , xn) = ---------------"
echo "                      n * SUM(xi ^ 2)"
echo "-----------------------------------------------------------------"
echo "-----------------------------------------------------------------"


if [ $# -eq 1 ]; then
	preprocessor.sh $1 .
	if [ $? -ne 0 ]; then
		exit 1
	fi
	cd results

	if [ ! -f 1.dat ]; then
		echo "Error. 1.dat file does not exist in the current directory. Quitting..."
		exit 1
	fi
	
else
	outer_dir="results_fairness_dir"
	mkdir $outer_dir 2> /dev/null
	for file in $@ 
	do
		mkdir "res_$file" && cp $file "res_$file"
	       	cd "res_$file"
		preprocessor.sh $file .
		cp results/1.dat ../$outer_dir/"$file.dat"
		cd ..
		rm -rf "res_$file"
	done
	cd $outer_dir
	gnuplot /usr/bin/*.plt
fi

n=0			# total number of .dat files
tputs=()	# Array of all throughputs (n files) 

for f in *.dat
do
	n=$((n+1))
	tput=`cut -d " " -f 5 $f | paste -sd+ - | bc`
	tputs+=("$tput")
done
#Here, we have tputs ready, with the sum of all throughputs

total=0
for i in ${tputs[@]}; do
  total=`echo "scale=5; $i + $total" | bc -l`
done

squared=0
for i in ${tputs[@]}; do
  squared=`echo "scale=5; $i^2 + $squared" | bc -l`
done

findex=`echo "scale=5; ($total^2)/($n*$squared)" | bc -l`

RED='\033[0;31m'
NC='\033[0m' 
printf "Fairness index=${RED}$findex${NC}\n"
echo "*****************************************************************"

if [ $# -ne 1 ]; then
	xdg-open throughput.pdf > /dev/null 2>&1
	rm -rf "../results_fairness_dir" 2> /dev/null
fi
