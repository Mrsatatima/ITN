from qgis.core import(QgsFeature, QgsVectorLayer,QgsFeatureRequest,
                      QgsFields,QgsApplication,QgsGeometry, QgsField,
                      QgsDistanceArea, QgsUnitTypes, QgsProcessingFeatureSourceDefinition)
from PyQt5.QtCore import  QVariant
from processing.core.Processing import Processing
import processing
import random
import os
import pandas as pd
from processing.tools import dataobjects

from helper import *

# QGIS install prefix: set the QGIS_PREFIX_PATH environment variable,
# e.g. "C:/Program Files/QGIS 3.32/apps/qgis" (Windows) or "/usr" (Linux)
path = os.environ.get("QGIS_PREFIX_PATH", "C:/Program Files/QGIS 3.32/apps/qgis")
QgsApplication.setPrefixPath(path, True)
qgs = QgsApplication([], False)

qgs.initQgis()
Processing.initialize()


def crt_subset_lyr(layer, query):
    """
        Creates a subset of a layer by pyqgis processing 
        selection by expression,
        Input:
            layer: The layer you want to get subset from (QgsVectorLayer)
            query: Expression to be ised for querying (str)
        Ouput:
            memory_layer: subset of the layer (QgsVectorLayer)

    """
    # Create a memory layer
    if layer.geometryType() == 2:
        set_extent_uri = f"Polygon?crs={layer.crs().authid()}"
    elif layer.geometryType() == 0:
        set_extent_uri = f"Point?crs={layer.crs().authid()}"
    else:
        set_extent_uri = f"Polyline?crs={layer.crs().authid()}"
    memory_layer = QgsVectorLayer(set_extent_uri, f"{layer.name()}", "memory")
    memory_layer.startEditing()
    # Set the memory layer's fields
    memory_layer.dataProvider().addAttributes(layer.dataProvider().fields().toList())
    memory_layer.updateFields()

    parameters = {'INPUT': layer,
                  'EXPRESSION': query,
                  'METHOD': 0,
                  }
    run_selection = processing.run('qgis:selectbyexpression', parameters)
    if run_selection['OUTPUT']:
        print("Selection successful")
    else:
        print("Selection failed")
    # Add the selected features to the memory layer
    selected = run_selection['OUTPUT'].selectedFeatures()
    for feature in selected:
        outFeat = QgsFeature()
        outFeat.setGeometry(feature.geometry())
        outFeat.setAttributes(feature.attributes())
        memory_layer.dataProvider().addFeatures([outFeat])
        memory_layer.updateExtents()
    # memory_layer.commitChanges()
    return memory_layer


def clip_set_ext_layer(layer, clip_layer):
    """
        this function clips features that are within another layer
        it uses the pyqgis processing clip
        Input:
            layer: The layer whose features needs to be clip (QgsVectorLayer)
            clip_layer: layer for to be used for cliping (QgsVectorLayer)
        Output:
            clipped_layer: Clipped features (QgsVectorLayer)
    """
    parameters = {'INPUT': layer,
                  'OVERLAY': clip_layer,
                  'OUTPUT': 'TEMPORARY_OUTPUT',
                  }
    context = dataobjects.createContext()
    context.setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck)
    clipped_layer = processing.run('native:clip', parameters, context=context)

    return clipped_layer["OUTPUT"]


def create_random_point(layer):
    """
        chooses the extent with the largest bld_count
        an create a random point within the extent
        Input:
            layer: Extents layers to choose largest from (QgsVectoLayer)
        Output:
        Point: The x and y coordinate of the point (tuple) 
    """
    extent_layer = layer.getFeatures()
    extents = [extent for extent in extent_layer]
    dct = {}
    for idx, extent in enumerate(extents):
        if extent["bld_count"] == "1-50" and 1 not in dct.values():
            dct[str(idx)] = 0
        elif extent["bld_count"] == "51-100" and 1 not in dct.values():
            dct[str(idx)] = 1
        elif extent["bld_count"] == "101-250" and 2 not in dct.values():
            dct[str(idx)] = 2
        elif extent["bld_count"] == "251-1000" and 3 not in dct.values():
            dct[str(idx)] = 3
        elif extent["bld_count"] == "1001 and up" and 4 not in dct.values():
            dct[str(idx)] = 4
        else:
            continue
    extent = extents[int(max(dct, key=dct.get))]
    extent_center = extent.geometry().centroid().asPoint()
    x = extent_center.x()
    y = extent_center.y()
    point = (x, y)
    return point


def geo_location(wards_layer, extent, state, lga, ward, lga_dct, ward_dct):
    """
        takes a ward and create a random point within the ward
        Input:
            wards_layer: GRID3 Nigeria wards layer (QgsVectorLayer)
            extent: GRID3 Nigeria settlemetn extents layer (QgsVectorLayer)
        Output:
            location: x and y coordinates of the location (tuple)
    """
    wards_layer = QgsVectorLayer(wards_layer, "wards", "ogr")
    extent = QgsVectorLayer(extent, "set_extent", "ogr")
    # print(ward_dct[ward.strip().lower()])
    query = f'"statename"  =  \'{state}\' AND  "lganame"  =  \'{lga_dct[lga.strip().lower()].title()}\'AND "wardname" = \'{ward_dct[lga.strip().lower()][ward.strip().lower()].title()}\''
    ward_layer = crt_subset_lyr(wards_layer, query)
    if list(ward_layer.getFeatures())[0]['status'] == "Invalid":
        return ("x",'y')
    ward_extent = clip_set_ext_layer(extent, ward_layer)
    location = create_random_point(ward_extent)
    return location


def convert_csv_to_layer(file_name):
    """
        this function converts a csv with x and y columns
        into a QgsLayer
        Input:
            file_name: file path of the csv file (str)
        Output:
            memory_layer: converterd csv (QgsLayer) 
    """
    uri= f'file:///{file_name}?delimiter=,&yField=Latitude&xField=Longitude'
    settlement_layer = QgsVectorLayer(uri, 'settlement', 'delimitedtext')
    memory_layer = QgsVectorLayer("Point?crs=EPSG:4326", 'memory_layer', 'memory')

    # Add the same fields to the memory layer
    memory_layer.dataProvider().addAttributes(settlement_layer.fields())
    memory_layer.updateFields()

    # Copy features from the delimited text layer to the memory layer
    memory_layer.startEditing()
    memory_layer.dataProvider().addFeatures(settlement_layer.getFeatures())
    memory_layer.commitChanges()
    return memory_layer


def within_ward_boundary(settlement_layer, ward_layer, lga_map, wards_map):
    """
        this function checks which settlments fall outside
        there respective ward boundary. it then adds new
        attribute to the settlement layer in_ward (Yes or No),
        dst_km (distance in Km it is from its original ward) and
        GRID3_wrd based on the GRID3 data base
        Input:
            settlement_layer: layer of settlements point whose accuracy are to
                            be check (QgsLayer)
            ward_layer: a layer of the ward boundaries from the state the
                        settlements belong to (QgsLayer)
            lga_map: A dictionary mapping the names of LGA in the settlement layer
                    and that of the ward_layer (dict)
            wards_map: A dictionary mapping the names of ward in the settlement layer
                    and that of the ward_layer (dict)
        Ouput:
            settlement_layer: A settlement layer with in_wards dst_km and GRID_wrd
                            attributes populated
    """
    fields = [
        QgsField('in_Ward', QVariant.String),
        QgsField('dst_km', QVariant.Double),
        QgsField('GRID3_Wrd', QVariant.String, len=35),
    ]

    settlement_layer.startEditing()
    layer_provider = settlement_layer.dataProvider()

    layer_provider.addAttributes(fields)

    settlement_layer.updateFields()
    print(settlement_layer.crs())

    dist = QgsDistanceArea()
    dist.willUseEllipsoid()
    dist.setEllipsoid(settlement_layer.crs().ellipsoidAcronym())
    print(QgsUnitTypes.toString(dist.lengthUnits()))

    for settlement in settlement_layer.getFeatures():
        ward_name = settlement['Ward']
        lga_name = settlement['LGA']
        expression = f'"lganame" = \'{lga_map[lga_name.lower()].title()}\''
        GRID3_ward = wards_map[lga_name.lower()][ward_name.lower()]
        wards = ward_layer.getFeatures(expression)
        
        ward_geom =None
        for ward in wards:
            if ward['wardname'].lower() == wards_map[lga_name.lower()][ward_name.lower()]:
                ward_geom = ward.geometry()
                break
        if ward_geom:
            settlement_geom = settlement.geometry()
            if ward_geom.contains(settlement_geom):
                in_ward = "Yes"
                dist_to_ward = 0.0
                
            else:
                in_ward = "No"
                nearest_ward_geom = ward_geom.nearestPoint(settlement_geom)
                dist_to_ward = dist.measureLine(settlement_geom.asPoint(), nearest_ward_geom.asPoint())/1000
           
            settlement_layer.changeAttributeValue(settlement.id(), settlement_layer.fields().lookupField('in_Ward'), in_ward)
            settlement_layer.changeAttributeValue(settlement.id(), settlement_layer.fields().lookupField('dst_km'), dist_to_ward)
            settlement_layer.changeAttributeValue(settlement.id(), settlement_layer.fields().lookupField('GRID3_Wrd'), GRID3_ward)
    settlement_layer.commitChanges()
    return settlement_layer


def convert_layer_to_dataframe(layer):
    """
        This function take a QgsLayer and convert it to a pandas 
        dataframe
        Input:
            layer: The layer you want to convert to 
                    pandas dataframe (QgsLayer)
        Output:
        df: the convert layer (pandas dataframe)
    """
    
    # Initialize an empty list to store feature attributes
    features_list = []

    # Iterate through features and collect attributes
    for feature in layer.getFeatures():
        feature_dict = dict(zip(feature.fields().names(), feature.attributes()))
        features_list.append(feature_dict)

    # Create a Pandas DataFrame from the list
    df = pd.DataFrame(features_list)

    return df