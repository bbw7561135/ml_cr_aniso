"""
The script takes an src_sample_...NsideXXX.txt.xz file
from data/sources/ and converts it to a similar file for another Nside.

"""

from __future__ import print_function, division

import sys
import os
import numpy as np
import healpy as hp
from backports import lzma

#______________________________________________________________________

# Nside in the initial file
Nside_ini = 256

#source_id = 'NGC253'
source_id = 'CenA'
#source_id = 'M82'
#source_id = 'M87'
#source_id = 'FornaxA'
#______________________________________________________________________

# Emin for which the input sample was generated
Emin = 8   # EeV

# Less used initial parameters
# healpix grid parameter
Nside = 512

# Radius of the vicinity of a source used when making a sample
source_vicinity_radius = 1

# Size of the initial sample of from-source events. It is used
# in the initial file name and when making a sample of src_frac*N_EECR
# IT SHOULD NOT BE MODIFIED UNLESS A NEW INPUT FILE IS CREATED
Nini = 100000

#______________________________________________________________________

if Nside==Nside_ini:
    print("Nside=Nside_ini, nothing to be done!")
    sys.exit()

#______________________________________________________________________
if source_id=='M82':
    source_lon = 141.4095
    source_lat = 40.5670
    D_src = '3.5'    # Mpc
elif source_id=='CenA':
    source_lon = 309.5159
    source_lat = 19.4173
    D_src = '3.5'    # Mpc
elif source_id=='NGC253':
    source_lon = 97.3638
    source_lat = -87.9645
    D_src = '3.5'    # Mpc
elif source_id=='NGC6946':
    source_lon = 95.71873
    source_lat = 11.6729
    D_src = '6.0'
elif source_id=='M87':
    source_lon = 283.7777
    source_lat = 74.4912
    D_src = '18.5'    # Mpc
elif source_id=='FornaxA':
    source_lon = 240.1627
    source_lat = -56.6898
    D_src = '20.0'    # Mpc
else:
    print('\nUnknown source!')
    sys.exit()

#______________________________________________________________________

# Input file name; the file must be prepared with src_sample.py
# It provides data for making a sample of from-source events
infile = ('src_sample_' + source_id + '_D' + D_src
        + '_Emin' + str(Emin)
        + '_N' + str(Nini)
        + '_R' + str(source_vicinity_radius) 
        + '_Nside' + str(Nside_ini) + '.txt.xz')

# File for individual spectra
outfile = ('src_sample_' + source_id + '_D' + D_src
        + '_Emin' + str(Emin)
        + '_N' + str(Nini)
        + '_R' + str(source_vicinity_radius) 
        + '_Nside' + str(Nside) + '.txt')


#______________________________________________________________________

# 1. Read a file produced by src_sample.py:
#    0        1        2        3       4     5  6     7
# lat_ini, lon_ini, lat_res, lon_res, angsep, Z, E, cell_no
#data = np.loadtxt('data/sources/'+infile)
try:
    with lzma.open('data/sources/'+infile,'rt') as f:
        data = np.genfromtxt(f,dtype=float)
except IOError:
    print('\n-------> data/sources/' + infile + ' file not found!\n')
    sys.exit()

# 2. Find non-zero lines, i.e., those with Z>0:
tp = np.arange(0,np.size(data[:,0]))
# These are indices of "nonzero nuclei" in the initial sample
nonz = tp[data[:,5]>0]

# Extract lat_ini, lon_ini (as arrival directions to Earth), and
# possibly E, Z; cell_no can/will be used when calculating the angular
# power spectrum.
lat_arr = np.deg2rad(data[nonz,0])
lon_arr = np.deg2rad(data[nonz,1])

# These are numbers of cells on the healpix grid.
healpix_cells  = hp.ang2pix(Nside,np.rad2deg(lon_arr),
        np.rad2deg(lat_arr),lonlat=True)

# Now we only have to write down the outfile and xz it.

header = ('#   lat_ini    lon_ini    lat_res    lon_res     angsep   '
          'Z   E   cell_no\n')

with open('data/sources/'+outfile,'w') as d:
    d.write(header)
    for i in np.arange(len(nonz)):
        d.write('{:11.5f}{:11.5f}{:11.5f}{:11.5f}{:11.5f}{:4d}{:5d}{:9d}\n'.
                format(data[i,0],data[i,1],
                   data[i,2],data[i,3],
                   data[i,4],int(data[i,5]),
                   int(data[i,6]),int(healpix_cells[i])))

os.system('xz data/sources/'+outfile)

