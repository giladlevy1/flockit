#!/bin/sh
# Capture every packet a running Flockit deployment sends and report anything that
# leaves the compose network. Run it next to your own deployment:
#
#   docker compose up -d
#   ./deploy/network-trace.sh 300     # capture for 300 seconds while you use Flockit
#
# Needs Docker. Builds a tiny tcpdump image first, so installing tcpdump does not
# pollute the capture.
set -eu

SECONDS_TO_CAPTURE="${1:-120}"
APP="$(docker compose ps -q flockit)"
NET="$(docker inspect "$APP" -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')"
BRIDGE="br-$(docker network inspect "$NET" -f '{{.Id}}' | cut -c1-12)"
APP_IP="$(docker inspect "$APP" -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
OUT="$(mktemp -d)"

printf 'FROM alpine:3.20\nRUN apk add --no-cache tcpdump\n' | docker build -q -t flockit-sniffer - >/dev/null
echo "Capturing on $BRIDGE (compose network $NET, app $APP_IP) for ${SECONDS_TO_CAPTURE}s..."
docker run -d --rm --name flockit-sniff --net host -v "$OUT:/pcap" flockit-sniffer \
  tcpdump -i "$BRIDGE" -nn -U -w /pcap/bridge.pcap >/dev/null
sleep "$SECONDS_TO_CAPTURE"
docker stop flockit-sniff >/dev/null

echo
echo "Connections opened BY the app, by destination:"
docker run --rm -v "$OUT:/pcap" flockit-sniffer sh -c \
  "tcpdump -nn -r /pcap/bridge.pcap 'src host $APP_IP and tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack == 0' 2>/dev/null | awk '{print \$5}' | sed -E 's/\\.[0-9]+:\$//' | sort | uniq -c"
echo
echo "Packets from the compose network to a public address, excluding replies to inbound :8080 traffic:"
docker run --rm -v "$OUT:/pcap" flockit-sniffer sh -c \
  "tcpdump -nn -r /pcap/bridge.pcap 'ip and not (dst net 172.16.0.0/12 or dst net 10.0.0.0/8 or dst net 192.168.0.0/16 or dst net 127.0.0.0/8) and not src port 8080' 2>/dev/null | wc -l"
echo
echo "Raw capture: $OUT/bridge.pcap"
