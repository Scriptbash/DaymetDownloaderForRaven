import os
import sys
import warnings
import argparse
import urllib.request
import numpy as np
import xarray as xr
import pandas as pd
import geopandas as gpd
from datetime import datetime, timedelta, timezone

warnings.filterwarnings("ignore", category=RuntimeWarning, module='xarray')

# MacOS users may need to follow these steps https://stackoverflow.com/a/62374703


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str,
                        help="Path to the watershed shapefile (required for spatial extraction of Daymet data).")
    parser.add_argument("-s", "--start", type=str,
                        help="Start date for the data download (format: YYYY-MM-DD).")
    parser.add_argument("-e", "--end", type=str,
                        help="End date for the data download (format: YYYY-MM-DD).")
    parser.add_argument("-v", "--variables", type=str,
                        help="Comma-separated list of climate variables to download (e.g., 'tmax,tmin,prcp').")
    parser.add_argument("-f", "--fix_nan",
                        help="Enable this flag to fix NaN values in the dataset "
                             "by averaging neighboring cells or using prior day's data.", action="store_true")
    parser.add_argument("-m", "--merge",
                        help="Merge all downloaded NetCDF files into a single output file "
                             "(per variable).", action="store_true")
    parser.add_argument("-o", "--output", type=str,
                        help="Path to save the processed data (output directory)")
    parser.add_argument("-t", "--timeout", type=int,
                        help="Maximum time (in seconds) to wait for network "
                             "requests before timing out. Default is 120 seconds.", default=120)

    args = parser.parse_args()
    check_input(args)


def check_input(args):
    variable_options = ['tmin', 'tmax', 'prcp']

    # Check for the watershed shapefile
    if not os.path.exists(args.input):
        print("Error: Watershed shapefile not found at the provided path.")
        sys.exit(1)

    # Check the start and end date
    try:
        datetime.strptime(args.start, "%Y-%m-%d")
        datetime.strptime(args.end, "%Y-%m-%d")
    except ValueError:
        print('Error: Incorrect date format. Expected format is: YYYY-MM-DD.')
        sys.exit(1)

    # Check for valid variables
    for variable in args.variables.split(','):
        if variable not in variable_options:
            print('Error: The variable entered is incorrect. The available choices are :\ntmin (minimum temperature)\n'
                  'tmax (maximum temperature)\nprcp (precipitation)')
            sys.exit(1)

    # Check for valid output folder and if it's writable
    if not os.path.exists(args.output):
        if not os.access(args.output, os.W_OK):
            print('Error: The output path provided is not writable.')
            sys.exit(1)
        else:
            os.makedirs(args.output)
            print('Output folder did not exist. One was created.')
    else:
        if not os.access(args.output, os.W_OK):
            print('Error: The output path provided is not writable.')
            sys.exit(1)

    options_dict = {
        'polygon_shp': args.input,
        'start': datetime.strptime(args.start, "%Y-%m-%d"),
        'end': datetime.strptime(args.end, "%Y-%m-%d"),
        'variables': args.variables.split(','),
        'nan_fix': args.fix_nan,
        'merge': args.merge,
        'output_folder': args.output,
        'timeout': args.timeout,
    }

    bounding_box = define_area(options_dict)
    get_data(options_dict, bounding_box)


def define_area(options):
    input_polygon = options['polygon_shp']
    gdf = gpd.read_file(input_polygon)
    crs = gdf.crs
    if crs.to_string() != 'EPSG:4326':
        print('CRS mismatch... input layer CRS is ' + crs.to_string())
        print('Reprojecting layer to EPSG:4326...')
        gdf = gdf.to_crs('EPSG:4326')
        print('Reprojection done.')

    print("Extracting bounding box...")
    bbox_list = []

    for i, row in gdf.iterrows():
        bbox = row.geometry.bounds  # Returns (xmin, ymin, xmax, ymax)
        bbox = [str(round(bbox[0], 2)), str(round(bbox[1], 2)),
                str(round(bbox[2], 2)), str(round(bbox[3], 2))]
        bbox_list.append(bbox)

    print('Bounding box extraction done.')
    return bbox_list


def get_data(options, bbox):
    timeout = options['timeout']
    region = "na"

    print('Initializing...')
    for i in range(len(bbox)):
        north = bbox[i][3]
        west = bbox[i][0]
        east = bbox[i][2]
        south = bbox[i][1]

        for variable in options['variables']:
            for year in range(int(options['start'].year), int(options['end'].year)+1):
                url = "https://thredds.daac.ornl.gov/thredds/ncss/grid/ornldaac/2129/daymet_v4_daily_" + region + "_" \
                        + variable + '_' + str(year) + ".nc?var=lat&var=lon&var=" + variable + '&north=' + north + \
                        "&west=" + west + "&east=" + east + "&south=" + south + \
                        "&disableProjSubset=on&horizStride=1&time_start=" + \
                        str(options['start'].date()) + "T12:00:00Z&time_end=" + str(options['end'].date()) + \
                      "T12:00:00Z&timeStride=1&accept=netcdf"
                req = urllib.request.Request(url)
                try:
                    response = urllib.request.urlopen(req, timeout=timeout)
                except TimeoutError:
                    print('Error: The request timed out. Consider increasing the timeout delay using the -t option')
                    sys.exit(1)
                totalsize = int(response.info()['Content-Length'])
                currentsize = 0
                old_percentage = 0
                chunk = 4096

                filename = str(year) + variable + '.nc'
                output_file = options['output_folder'] + "/" + filename
                print("Variable " + str(options['variables'].index(variable) + 1) + "/" +
                      str(len(options['variables'])) + " - Downloading " + filename)
                with open(output_file, 'wb') as file:
                    while 1:
                        data = response.read(chunk)
                        if not data:
                            break
                        file.write(data)
                        currentsize += chunk
                        if totalsize > 0:
                            download_percentage = (currentsize / totalsize) * 100
                            if int(download_percentage) > old_percentage:
                                print(f"\rDownload progress: {int(download_percentage)}%", end='', flush=True)
                                old_percentage = int(download_percentage)
                print()
                if options['nan_fix']:
                    missing_dates = check_missing_dates(output_file)
                    fix_missing_values(output_file, missing_dates, variable)
                else:
                    pass
            if options['merge']:
                merge_netcdf(options['output_folder'], variable)
        print("Download complete!")


def merge_netcdf(file_path, variable):
    try:
        print('Merging files...')
        ds = xr.open_mfdataset(file_path + '/*' + variable + '.nc', parallel=False)
        # Round down the time values to the nearest integer (remove the 0.5)
        ds['time'] = ds['time'].dt.floor('D')
        # Remove the time dimension from the lat and lon variables
        lat_without_time = ds['lat'].isel(time=0)
        lon_without_time = ds['lon'].isel(time=0)
        ds_modified = xr.Dataset({
            'lat': lat_without_time,
            'lon': lon_without_time,
            variable: ds[variable]
        })
        ds_modified.to_netcdf(file_path + '/' + variable + '_merged.nc')
        ds.close()
        ds_modified.close()
        print('Merge complete.')
    except Exception as e:
        print('The merging attempt failed. Manual processing will be required.')
        print(e)
        return


def check_missing_dates(ncfile):
    ds = xr.open_dataset(ncfile)
    time_data = ds['time'].values
    start_date = pd.Timestamp(time_data.min())
    end_date = pd.Timestamp(time_data.max())
    datetime_list = [datetime.fromtimestamp(ts.astype('O') / 1e9, timezone.utc).replace(tzinfo=None)
                     for ts in time_data]

    start_date = datetime(start_date.year, start_date.month, start_date.day, 12, 0)
    end_date = datetime(end_date.year, end_date.month, end_date.day, 12, 0)

    all_dates = [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]

    missing_dates = [date for date in all_dates if date not in datetime_list]
    ds.close()
    return missing_dates


def fix_missing_values(ncfile, missing_dates, variable):
    ds = xr.open_dataset(ncfile)

    if variable == 'prcp':
        if missing_dates:
            # Create an empty DataArray with NaN values for the missing dates
            missing_data = xr.full_like(ds.isel(time=0), fill_value=float(0.0))
            missing_data['time'] = missing_dates
            # Concatenate the missing data with the ds along the 'time' dimension
            updated_data = xr.concat([ds, missing_data], dim='time')
            updated_data = updated_data.fillna(float(0.0))
            # updated_data.to_netcdf(ncfile)
        else:
            updated_data = ds.fillna(float(0.0))
            # updated_data.to_netcdf('./result/test.nc')
    else:
        if ds.isnull().any():
            print('Found NaN values. Attempting to fix...')
            try:
                radius = 1
                # Find indices of missing values
                missing_indices = np.argwhere(np.isnan(ds[variable].values))

                for idx in missing_indices:
                    time_idx, lat_idx, lon_idx = idx

                    # Find neighboring values within the radius
                    y_slice = slice(max(lat_idx - radius, 0), min(lat_idx + radius + 1, len(ds['y'])))
                    x_slice = slice(max(lon_idx - radius, 0), min(lon_idx + radius + 1, len(ds['x'])))
                    neighbor_values = ds[variable].isel(time=time_idx, y=y_slice, x=x_slice)

                    # Exclude NaN values and compute the mean
                    neighbor_mean = np.nanmean(neighbor_values)

                    # Fill missing values with the mean of neighboring values
                    ds[variable].values[time_idx, lat_idx, lon_idx] = neighbor_mean
                print('Done.')
            except Exception as e:
                print('Unable to fix the NaN values.')
                print(e)

        if missing_dates:
            missing_data = xr.full_like(ds.isel(time=0), fill_value=np.nan, dtype=float)
            missing_data['time'] = missing_dates
            # Concatenate the missing data with the ds along the 'time' dimension
            updated_data = xr.concat([ds, missing_data], dim='time')
            for date in missing_dates:
                try:
                    # Attempt to extract values for the day before and day after
                    # Find nearest available dates (day before and day after)
                    before_date = (pd.to_datetime(date) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                    after_date = (pd.to_datetime(date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

                    if before_date in [str(ts)[:10] for ts in updated_data.time.values] and \
                            after_date in [str(ts)[:10] for ts in updated_data.time.values]:
                        before_values = updated_data[variable].sel(time=before_date, method='nearest').values
                        after_values = updated_data[variable].sel(time=after_date, method='nearest').values
                        if not np.any(np.isnan(before_values)) and not np.any(np.isnan(after_values)):
                            # Calculate the average
                            average_value = (before_values + after_values) / 2.0
                            # Assign the average value to the missing date
                            updated_data[variable].loc[dict(time=date)] = average_value
                            print('Using average of the day before and the day after for interpolation.')
                            continue

                    before_date = (pd.to_datetime(date) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                    after_date = (pd.to_datetime(date) - pd.Timedelta(days=2)).strftime('%Y-%m-%d')
                    if before_date in [str(ts)[:10] for ts in updated_data.time.values] and \
                            after_date in [str(ts)[:10] for ts in updated_data.time.values]:
                        before_values = updated_data[variable].sel(time=before_date, method='nearest').values
                        after_values = updated_data[variable].sel(time=after_date, method='nearest').values
                        if not np.any(np.isnan(before_values)) and not np.any(np.isnan(after_values)):
                            # Calculate the average
                            average_value = (before_values + after_values) / 2.0
                            # Assign the average value to the missing date
                            updated_data[variable].loc[dict(time=date)] = average_value
                            print('Using average of the two days before for interpolation.')
                            continue

                    before_date = (pd.to_datetime(date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                    after_date = (pd.to_datetime(date) + pd.Timedelta(days=2)).strftime('%Y-%m-%d')
                    if before_date in [str(ts)[:10] for ts in updated_data.time.values] and \
                            after_date in [str(ts)[:10] for ts in updated_data.time.values]:
                        before_values = updated_data[variable].sel(time=before_date, method='nearest').values
                        after_values = updated_data[variable].sel(time=after_date, method='nearest').values
                        if not np.any(np.isnan(before_values)) and not np.any(np.isnan(after_values)):
                            # Calculate the average
                            average_value = (before_values + after_values) / 2.0
                            # Assign the average value to the missing date
                            updated_data[variable].loc[dict(time=date)] = average_value
                            print('Using average of the two days after for interpolation.')
                            continue
                    print('Missing values are present. Could not interpolate.')

                except KeyError:
                    print(f"No data available for {date}. Skipping.")

        else:
            updated_data = ds

    updated_data.to_netcdf(ncfile)
    updated_data.close()

    ds.close()


if __name__ == "__main__":
    main()
