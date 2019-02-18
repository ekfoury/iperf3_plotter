# iperf3_plotter
Shell script that plots iPerf3's JSON file

## About
This is a simple shell script that accepts the JSON output of iPerf3 and plots the results using gnuplot.
Basically, there are two shell scripts: 

### preprocessor.sh
This script converts iPerf3's JSON file to a Comma-separated value (CSV) file. It also uses AWK to format the fields.


### plot_iperf.sh
This script accepts iPerf3's JSON file, calls preprocessor, and calls gnuplot to create PDF outputs for the following fields extracted from the JSON file:
- socket
- start
- end
- start
- seconds
- seconds
- bytes
- bits_per_second
- retransmits
- snd_cwnd
- rtt
- rttvar
- pmtu
- omitted

## Install
This script requires jq and gnuplot.
Run the following command in the script's directory. It installs the dependencies, and makes the scripts accessible anywhere.
```bash
sudo make
```

## Usage
```bash
preprocessor.sh <iperf_json_input> <output_directory>
Example: preprocessor.sh my_test.json simulation_results
```

```bash
plot_iperf.sh <iperf_json_file>
Example: plot_iperf.sh my_test.json
```
### Sample run in mininet:
1. Launch mininet and create your topology
2. Launch the xterms of the hosts
3. Start the iPerf3 server:
```bash
iperf3 -s
```
4. Start the iPerf3 client: (-J to create a JSON output, -P to start multiple flows, -t to specify the transmission time, and finally, redirect the stdout to a file).
```bash
iperf3 -c 10.0.0.2 -J -P 4 -t 60 > my_test.json
```
5. Use the plot_iperf.sh script to generate the output. This will create a results directory containing the plots of all fields.
```bash
iperf_plot.sh my_test.json
```
Test the script on the my_test.json file provided in the sample directory

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.
