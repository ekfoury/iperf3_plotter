#!/bin/bash

# This script reads a JSON file exported from iPerf3 that has multiple parallel streams, 
# and calculate the fairness index according to Raj Jain's formula:
# Fairness index = [(sum xi)**2] / {n * sum[(xi)**2]}


preprocessor.sh $1 .

if [ $? -ne 0 ]; then
	exit 1
fi

cd results


if [ ! -f 1.dat ]; then
	echo "Error. 1.dat file does not exist in the current directory. Quitting..."
	exit 1
fi

echo "*****************************************************************"
echo "This script calculates the fairness index among parallels streams"
echo "-----------------------------------------------------------------"
echo "                         SUM(xi)^2"
echo "F(x1, x2, ... , xn) = ---------------"
echo "                      n * SUM(xi ^ 2)"
echo "-----------------------------------------------------------------"
echo "-----------------------------------------------------------------"


#fair4=`echo "scale=5; (($mean1 + $mean2 + $mean3 + $mean4) ^ 2) / (4 * ($mean1 ^ 2 + $mean2 ^2 + $mean3 ^ 2 + $mean4 ^ 2))" | bc -l`

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
echo "Fairness index=$findex"
echo "*****************************************************************"
