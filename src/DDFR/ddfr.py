import os
import sys
import warnings
import argparse
import urllib.request
import numpy as np
import xarray as xr
import pandas as pd
import geopandas as gpd
from DDFR import generate_simple_weights
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
                        help="Comma-separated list of climate variables to download "
                             "(e.g., 'tmax,tmin,prcp,swe,srad,vp,dayl').")
    parser.add_argument("-f", "--fix_nan",
                        help="Enable this flag to fix NaN values in the dataset "
                             "by averaging neighboring cells or using prior day's data.", action="store_true")
    parser.add_argument("-m", "--merge",
                        help="Merge all downloaded NetCDF files into a single output file "
                             "(per variable).", action="store_true")
    parser.add_argument("-g", "--gridweights",
                        help="Generate a text file containing grid weights for Raven", action="store_true")
    parser.add_argument("-o", "--output", type=str,
                        help="Path to save the processed data (output directory)")
    parser.add_argument("-c", "--convert", type=str,
                        help="Converts the output into a csv, rvt or txt file. (e.g, 'csv', 'rvt', 'txt')")
    parser.add_argument("-t", "--timeout", type=int,
                        help="Maximum time (in seconds) to wait for network "
                             "requests before timing out. Default is 120 seconds.", default=120)

    args = parser.parse_args()
    check_input(args)


def check_input(args):
    variable_options = ['tmin', 'tmax', 'prcp', 'swe', 'srad', 'vp', 'dayl']
    conversion_options = ['csv', 'rvt', 'txt']

    # Check for the watershed shapefile
    if not os.path.exists(args.input):
        print("Error: Watershed shapefile not found at the provided path.")
        sys.exit(1)

    # Check the start and end date
    try:
        input_start_date = datetime.strptime(args.start, "%Y-%m-%d")
        input_end_date = datetime.strptime(args.end, "%Y-%m-%d")
        start_limit = datetime(1980, 1, 1)
        end_limit = datetime(2023, 12, 31)

        if not (start_limit <= input_start_date <= end_limit):
            print(f"Error: Start date {args.start} is not within the allowed range (1980-01-01 to 2023-12-31).")
            sys.exit(1)

        if not (start_limit <= input_end_date <= end_limit):
            print(f"Error: End date {args.end} is not within the allowed range (1980-01-01 to 2023-12-31).")
            sys.exit(1)
    except ValueError:
        print('Error: Incorrect date format. Expected format is: YYYY-MM-DD.')
        sys.exit(1)

    # Check for valid variables
    for variable in args.variables.split(','):
        if variable not in variable_options:
            print('Error: The variable entered is incorrect. The available choices are :\ntmin (minimum temperature)\n'
                  'tmax (maximum temperature)\nprcp (precipitation)\nswe (snow water equivalent)\n'
                  'srad (shortwave radiation)\nvp (vapor pressure)\ndayl (day length)')
            sys.exit(1)

    # Check for valid conversion option
    if args.convert and not args.merge:
        print("Error: The convert option requires to enable merging of the files. Please use the '-m' option.")
        sys.exit(1)
    elif args.convert not in conversion_options:
        print("Error: The conversion option is incorrect. The available options are 'csv', 'rvt' and 'txt'")
        sys.exit(1)

    # Check for valid output folder and if it's writable
    if not os.path.exists(args.output):
        if not os.access(args.output, os.W_OK):
            try:
                os.makedirs(args.output)
                print('Output folder did not exist. One was created.')
            except:
                print('Error: The output path provided is not writable.')
                sys.exit(1)
    else:
        if not os.access(args.output, os.W_OK):
            print('Error: The output path provided is not writable.')
            sys.exit(1)

    # Ignore gridweights flag if conversion option is provided
    if args.convert and args.gridweights:
        print("Warning: The gridweights flag was provided, but cannot be used with the conversion option. "
              "Ignoring the gridweights flag.")
        args.gridweights = False

    options_dict = {
        'polygon_shp': args.input,
        'start': datetime.strptime(args.start, "%Y-%m-%d"),
        'end': datetime.strptime(args.end, "%Y-%m-%d"),
        'variables': args.variables.split(','),
        'nan_fix': args.fix_nan,
        'merge': args.merge,
        'gridweights': args.gridweights,
        'output_folder': args.output,
        'output_format': args.convert,
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
    bbox = gdf.total_bounds  # Returns (xmin, ymin, xmax, ymax)

    bbox = [str(round(coord, 4)) for coord in bbox]
    
    return bbox


def get_data(options, bbox):
    timeout = options['timeout']
    region = "na"

    print('Initializing...')
    north = bbox[3]
    west = bbox[0]
    east = bbox[2]
    south = bbox[1]

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
                missing_dates = check_missing_dates(options['start'],options['end'], output_file)
                fix_missing_values(output_file, missing_dates, variable)
            else:
                pass
        if options['merge']:
            if int(options['end'].year) - int(options['start'].year) > 0:
                merge_netcdf(options['output_folder'], variable)
            else:
                print('Skipping merge as there is only one year.')
    if options['output_format']:
        convert_output(options['output_format'], options['variables'], options['output_folder'])
    if options['gridweights'] and options['merge'] and int(options['end'].year) - int(options['start'].year) > 0:
        generate_simple_weights(variable, options['polygon_shp'], options['output_folder'], True)
    elif options['gridweights'] and not options['merge'] or int(options['end'].year) - int(options['start'].year) < 1:
        generate_simple_weights(filename, options['polygon_shp'], options['output_folder'], False)
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


def check_missing_dates(start_date, end_date, ncfile):
    ds = xr.open_dataset(ncfile)
    time_data = ds['time'].values

    start_year = pd.Timestamp(time_data.min())
    end_year = pd.Timestamp(time_data.max())
    datetime_list = [datetime.fromtimestamp(ts.astype('O') / 1e9, timezone.utc).replace(tzinfo=None)
                     for ts in time_data]
    
    start_date = datetime(start_year.year, start_date.month, start_date.day, 12, 0)
    end_date = datetime(end_year.year, end_date.month, end_date.day, 12, 0)
   
    all_dates = [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]

    missing_dates = [date for date in all_dates if date not in datetime_list]
    ds.close()
    return missing_dates


def fix_missing_values(ncfile, missing_dates, variable):
    ds = xr.open_dataset(ncfile)

    if variable == 'prcp' or variable == 'swe':
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

def convert_output(file_format, variables, output_path):
    # TODO Clip the ncfiles with the shapefile
    output_file = os.path.join(output_path,f"forcing.{file_format}")
    all_averages = pd.DataFrame()
    raven_forcing_types = {'tmin': 'TEMP_MIN',
                           'tmax': 'TEMP_MAX',
                           'prcp': 'PRECIP',
                           'dayl': 'DAY_LENGTH',    # convert seconds to days
                           'srad': 'SHORTWAVE', # need to use dayl to convert to daily
                           'swe': 'SWE', # Unsupported as input data for Raven
                           'vp': 'VAPOR_PRESSURE' # Unsupported as input data for Raven
                           }
    units_dict = {
        'PRECIP': 'mm/d',
        'TEMP_MIN': 'DegC',
        'TEMP_MAX': 'DegC',
        'DAY_LENGTH': 'd',
        'SHORTWAVE': 'MJ/m2/d',
        'SWE': 'kg/m2',
        'VAPOR_PRESSURE': 'Pa'
    }

    def calculate_average():
        spatial_dims = [dim for dim in ds.dims if dim not in ['time']]
        return ds.mean(dim=spatial_dims)


    for variable in variables:
        nc_file_path = str(os.path.join(output_path, f"{variable}_merged.nc"))
        ds = xr.open_dataset(nc_file_path)
        average_values = calculate_average()
        averages_df = average_values.to_dataframe().reset_index()
        averages_df = averages_df.drop(columns=['lat', 'lon'], errors='ignore')
        if all_averages.empty:
            all_averages = averages_df
        else:
            all_averages = pd.merge(all_averages, averages_df, how='outer', on='time')
        ds.close()

    all_averages = all_averages.round(2)

    # Write the dataframe to a file
    if file_format == 'csv':
        all_averages.to_csv(output_file, index=False)
    elif file_format == 'txt':
        all_averages.to_csv(output_file, sep='\t', index=False)
    elif file_format == 'rvt':
        # Convert W/m2 to MJ/m2/d using day length in seconds per day
        if 'srad' in all_averages.columns and 'dayl' in all_averages.columns:
            all_averages['srad'] = (all_averages['srad'] * all_averages['dayl']) / 1_000_000
        elif 'srad' in all_averages.columns and 'dayl' not in all_averages.columns:
            print('Warning: The shortwave radiation is not using the proper units for Raven.'
                  'Current units are W/m2, but Raven expects MJ/m2/d.')
        # Convert seconds/day to days
        if 'dayl' in all_averages.columns:
            all_averages['dayl'] = all_averages['dayl'] / 86400
        for column in all_averages.columns:
            # Rename the variable if it's in the raven_forcing_types dictionary
            if column in raven_forcing_types:
                if column == 'swe' or column == 'vp':
                    print(f'Warning: the variable{column} is not supported as an input data for Raven, but it was still written to the file.')
                all_averages.rename(columns={column: raven_forcing_types[column]}, inplace=True)

        # Prepare header for the :MultiData section
        timestamp = all_averages['time'].iloc[0]  # First timestamp
        num_rows = len(all_averages)  # Number of observations
        parameters = [col for col in all_averages.columns if col != 'time']
        parameters_line = ' '.join(parameters)
        units_line = '   '.join([units_dict.get(raven_forcing_types.get(param, param), 'Unknown') for param in parameters])
        header = f":MultiData\n  {timestamp} 1.0 {num_rows}\n  :Parameters {parameters_line}\n  :Units {units_line}\n"

        with open(output_file, 'w') as f:
            f.write(header)
            all_averages.drop(columns=['time'], inplace=True)
            all_averages.to_csv(f, sep='\t', index=False, header=False)
    else:
        print("Error: Invalid file format option.")
        sys.exit(1)


if __name__ == "__main__":
    main()
