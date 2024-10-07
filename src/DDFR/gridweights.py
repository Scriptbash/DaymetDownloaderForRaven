import os
import geopandas as gpd
import xarray as xr
from shapely.geometry import Point


def generate_simple_weights(variable, shapefile, output_folder, merge):
    if merge:
        nc_file = os.path.join(output_folder, f"{variable}_merged.nc")
    else:
        nc_file = os.path.join(output_folder, variable)
    output_file = os.path.join(output_folder, "gridweights.txt")

    ds = xr.open_dataset(nc_file)

    # Create a list to store the point geometries and their corresponding cell numbers
    points = []
    cell_numbers = []  # List to store cell numbers

    # Iterate over each grid cell using its (y, x) indices to get corresponding lat/lon
    cell_number = 0

    if merge:
         # Extract the 2D latitude and longitude arrays
        lats = ds['lat'].values 
        lons = ds['lon'].values
        for i in range(lats.shape[0]):  # Iterate over rows (y dimension)
            for j in range(lats.shape[1]):  # Iterate over columns (x dimension)
                points.append(Point(lons[i, j], lats[i, j]))
                cell_numbers.append(cell_number)
                cell_number += 1
    else:
        lats = ds['lat'].isel(time=0).values  # Use the first time step
        lons = ds['lon'].isel(time=0).values

        # Iterate over the lat/lon arrays
        for i in range(lats.shape[0]):  # Iterate over rows (y dimension)
            for j in range(lats.shape[1]):  # Iterate over columns (x dimension)
                points.append(Point(lons[i, j], lats[i, j]))
                cell_numbers.append(cell_number)
                cell_number += 1

    # Create a GeoDataFrame with the points
    grid_gdf = gpd.GeoDataFrame({'cell_number': cell_numbers, 'geometry': points}, crs="EPSG:4326")
    
    # Read the watershed shapefile
    watershed_gdf = gpd.read_file(shapefile)
    watershed_gdf = watershed_gdf.to_crs('EPSG:4326')
    watershed_gdf.columns = [col.lower() for col in watershed_gdf.columns]
    number_hrus = len(watershed_gdf)

    if number_hrus == 1:
        # Keep only the points within the watershed polygon
        points_within_watershed = gpd.sjoin(grid_gdf, watershed_gdf, how='inner', predicate='within')
        # Count the number of cells within the watershed
        num_cells_inside_polygon = len(points_within_watershed)    
        with open(output_file, 'w') as f:
            f.write(':GridWeights\n:NumberHRUs\t1')
            f.write('\n:NumberGridCells\t' + str(len(grid_gdf)) + '\n')
            for cell_number in points_within_watershed['cell_number']:
                # Write the cell number and corresponding weight
                f.write("1\t{}\t{:.12f}\n".format(cell_number, number_hrus / num_cells_inside_polygon))
            f.write(':EndGridWeights')
    else:
        if 'hru_id' in watershed_gdf.columns:
            hru_id_column = "hru_id"
        elif 'id' in watershed_gdf.columns:
            hru_id_column = "id"
        else:
            print("HRU ID column not found. The grid weights file was not created.")
            return
            
        # Spatial join to assign HRU IDs to the points
        points_within_watershed = gpd.sjoin(grid_gdf, watershed_gdf[['geometry', hru_id_column]], how='inner', predicate='within')
        with open(output_file, 'w') as f:
            f.write(':GridWeights\n')
            f.write(f':NumberHRUs\t{number_hrus}\n')
            f.write(f':NumberGridCells\t{len(grid_gdf)}\n')
            # Group by HRU ID and calculate weights
            for hru_id, group in points_within_watershed.groupby(hru_id_column):
                num_cells_inside_polygon = len(group)  
                # Write each cell within the HRU polygon
                for cell_number in group['cell_number']:
                    f.write(f"{hru_id}\t{cell_number}\t{1 / num_cells_inside_polygon:.12f}\n")
            f.write(':EndGridWeights')
    ds.close()
    print(f"Grid weights file created: {output_file}")
