# Daymet downloader for Raven
Download and process Daymet data for use in the Raven hydrological modelling framework.

## Features
 - Download Daymet data for precipitation and minimum/maximum temperature using only a polygon shapefile.
 - Fix NaN values and insert missing dates
 - Merge the downloaded files
 - (Planned) Generate grid weights

## Usage

```python
ddfr [-h] [-i INPUT] [-s START] [-e END] [-v VARIABLES] [-f] [-m] [-o OUTPUT] [-t TIMEOUT]
```
Options:
```
  -h, --help                            - Show this help message and exit.
  -i INPUT, --input                     - Path to the watershed shapefile
                                          (required for spatial extraction of Daymet data).
  -s START, --start START               - Start date for the data download (format: YYYY-MM-DD).
  -e END, --end END                     - End date for the data download (format: YYYY-MM-DD).
  -v VARIABLES, --variables VARIABLES   - Comma-separated list of climate variables to download (e.g., 'tmax,tmin,prcp').
  -f, --fix_nan                         - [optional] Enable this flag to fix NaN values in the dataset by
                                          averaging neighboring cells or using prior day's data.
  -m, --merge                           - [optional Merge all downloaded NetCDF files into a single output
                                          file (per variable).
  -o OUTPUT, --output OUTPUT            - Path to save the processed data (output directory)
  -t TIMEOUT, --timeout TIMEOUT         - [optional] Maximum time (in seconds) to wait for network requests
                                          before timing out. Default is 120 seconds.
```
## Usage examples

Download minimum temperature and precipitation without processing:

```python
ddfr -i '/Users/francis/Documents/watershed.shp' -s 2010-01-01 -e 2012-12-31 -v 'tmin,precip' -o '/Users/francis/Documents/output'
```

Download minimum temperature and precipitation with processing:

```python
ddfr -i '/Users/francis/Documents/watershed.shp' -s 2010-01-01 -e 2012-12-31 -v 'tmin,precip' -f -m -o '/Users/francis/Documents/output'
```

Download maximum temperature and increase the request timeout:

```python
ddfr -i '/Users/francis/Documents/watershed.shp' -s 2010-01-01 -e 2012-12-31 -v 'tmax' -o '/Users/francis/Documents/output' -t 360
```