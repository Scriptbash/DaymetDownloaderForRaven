import os
import geopandas as gpd
import xarray as xr
from shapely.geometry import Point


def generate_simple_weights(variable, shapefile, output_folder):
    nc_file = os.path.join(output_folder, f"{variable}_merged.nc")
    output_file = os.path.join(output_folder, "gridweights.txt")

    ds = xr.open_dataset(nc_file)

    # Extract the 2D latitude and longitude arrays
    lats = ds['lat'].values 
    lons = ds['lon'].values

    # Create a list to store the point geometries and their corresponding cell numbers
    points = []
    cell_numbers = []  # List to store cell numbers

    # Iterate over each grid cell using its (y, x) indices to get corresponding lat/lon
    cell_number = 0
    for i in range(lats.shape[0]):  # Iterate over rows (y dimension)
        for j in range(lats.shape[1]):  # Iterate over columns (x dimension)
            # Create a Point geometry using the latitude and longitude at each cell
            points.append(Point(lons[i, j], lats[i, j]))
            cell_numbers.append(cell_number)
            cell_number += 1

    # Create a GeoDataFrame with the points
    grid_gdf = gpd.GeoDataFrame({'cell_number': cell_numbers, 'geometry': points}, crs="EPSG:4326")

    # Read the watershed shapefile
    watershed_gdf = gpd.read_file(shapefile)
    watershed_gdf = watershed_gdf.to_crs('EPSG:4326')

    # Keep only the points within the watershed polygon
    points_within_watershed = gpd.sjoin(grid_gdf, watershed_gdf, how='inner', predicate='within')

    # Count the number of cells within the watershed
    num_cells_inside_polygon = len(points_within_watershed)

    # Write the grid weights
    with open(output_file, 'w') as f:
        f.write(':GridWeights\n:NumberHRUs\t1')
        f.write('\n:NumberGridCells\t' + str(len(grid_gdf)) + '\n')
        for cell_number in points_within_watershed['cell_number']:
            # Write the cell number and corresponding weight
            f.write("1\t{}\t{:.12f}\n".format(cell_number, 1 / num_cells_inside_polygon))
        f.write(':EndGridWeights')

    print(f"Grid weights file created: {output_file}")
