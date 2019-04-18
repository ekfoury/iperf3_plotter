install: packages
	cp preprocessor.sh /usr/bin
	cp plot_iperf.sh /usr/bin
	cp plot_* /usr/bin
	cp fairness.sh /usr/bin
packages:
	apt-get install iperf3
	apt-get install jq
	apt-get	install gnuplot

