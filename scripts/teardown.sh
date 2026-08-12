#!/usr/bin/env bash
#
# teardown.sh
#
# Intent: delete all benchmark GPU instances at the end of a session, so
# nothing keeps billing after a run. Eventually this will shell out to
# something like:
#
#   gcloud compute instances delete <instance-names> --zone <zone> --quiet
#
# for every instance tagged as part of this project's benchmark fleet.

echo "TODO: implement teardown"
