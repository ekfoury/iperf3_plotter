FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    iperf3 \
    iproute2 \
    iputils-ping \
    mininet \
    net-tools \
    openvswitch-switch \
    procps \
    python3 \
    sudo \
    tcpdump \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

CMD ["/bin/bash"]

