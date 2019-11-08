#!/usr/bin/env python

from pathlib import Path

#-------- CONFIG Additional -----------------------#
# INPUTs
# - config file (yaml)
# - topo   file (prmtop)
system_name   = "aprotein"

#--------- SETUP with Input Files------------------#
# Path Objects
#cwd         = __file__.path ## modulefile path
cwd           = Path.cwd()   ## runtime    path
input_prefix  = cwd / "T0968s2_example_output"
output_prefix = cwd / "omm_systems"
system_file   = output_prefix / ("system-%s.xml" % system_name)

if not output_prefix.is_dir():
    output_prefix.mkdir()
