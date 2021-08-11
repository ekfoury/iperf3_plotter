install: packages
	cp preprocessor.sh /usr/bin
	cp plot_iperf.sh /usr/bin
	cp plot_* /usr/bin
	cp fairness.sh /usr/bin
packages:
	apt-get -y install iperf3 jq gnuplot
