#!/usr/bin/env python
import sys
import os
import configparser

########################################################################################################################
# Check if in Docker
IS_IN_DOCKER = os.environ.get('IS_IN_DOCKER')

########################################################################################################################
def config_section_map(section):
    'Load the config file into a dictionary'
    dict1 = {}
    options = config.options(section)
    for option in options:
        try:
            dict1[option] = config.get(section, option)
        except:
            print("exception on %s!" % option)
            dict1[option] = None
    return dict1

def cast(value, type_):
    return type_(value)

def get_config_value(key, config_section, is_mandatory, datatype, default_value = None):
    'Return for each key the corresponding value from the Docker Environment or the Config File'
    if IS_IN_DOCKER:
        config_value = os.environ.get(key)
        if config_value is not None: 
            # print(f'The value retrieved for [{config_section}]: {key} is "{config_value}"')
            config_value = config_value
            # return config_value
        elif is_mandatory:
            print(f'[ ERROR ]: Variable not specified in Docker environment: {key}' )
            sys.exit(0)
        else:
            # return default_value
            config_value = default_value

    else:
        try:
            config_value = config_section_map(config_section).get(key)
        except configparser.NoSectionError:
            config_value = None
        if config_value is not None:
            # print(f'The value retrieved for [{config_section}]: {key} is "{config_value}"')
            config_value = config_value  
            # return config_value
        elif is_mandatory:
            print(f'[ ERROR ]: Mandatory variable not specified in config file, section [{config_section}]: {key} (data type: {datatype.__name__})')
            sys.exit(0)
        else:
            # return default_value 
            config_value = default_value

    # Apply data type
    try:
        if datatype == bool:
            config_value = eval(str(config_value).capitalize())
        if config_value is not None: config_value = cast(config_value, datatype)
    except:
        print(f'[ ERROR ]: The value retrieved for [{config_section}]: {key} is "{config_value}" and cannot be converted to data type {datatype}')
        sys.exit(0)
    return config_value    

########################################################################################################################
# Load Config File
config_file_name = 'config.conf'
config_file_full_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), config_file_name)
sys.tracebacklimit = 0  # dont show stack traces in prod mode
config = configparser.ConfigParser()
config.optionxform = str # maintain capitalization of config keys
config.read(config_file_full_path)

########################################################################################################################
# Load Config
# General
LOG_LEVEL                   = get_config_value('LOG_LEVEL',                     'general',      False,  str,    'INFO')
TEST_RUN                    = get_config_value('TEST_RUN',                      'general',      False,  bool,   False)

# Features
REMOVE_TIMER                = get_config_value('REMOVE_TIMER',                  'features',     False,  int,    10)
REMOVE_FAILED               = get_config_value('REMOVE_FAILED',                 'features',     False,  bool,   False)
REMOVE_STALLED              = get_config_value('REMOVE_STALLED',                'features',     False,  bool,   False)
REMOVE_METADATA_MISSING     = get_config_value('REMOVE_METADATA_MISSING',       'features',     False,  bool,   False)
REMOVE_ORPHANS              = get_config_value('REMOVE_ORPHANS' ,               'features',     False,  bool,   False)
REMOVE_UNMONITORED          = get_config_value('REMOVE_UNMONITORED' ,           'features',     False,  bool,   False)
MIN_DOWNLOAD_SPEED          = get_config_value('MIN_DOWNLOAD_SPEED',            'features',     False,  int,    0)
PERMITTED_ATTEMPTS          = get_config_value('PERMITTED_ATTEMPTS',            'features',     False,  int,    3)
NO_STALLED_REMOVAL_QBIT_TAG = get_config_value('NO_STALLED_REMOVAL_QBIT_TAG',   'features',     False,  str,   'Don\'t Kill If Stalled')
NO_SLOW_REMOVAL_QBIT_TAG    = get_config_value('NO_SLOW_REMOVAL_QBIT_TAG',      'features',     False,  str,   'Don\'t Kill If Slow')

# Radarr
RADARR_URL                  = get_config_value('RADARR_URL',                    'radarr',       False,  str)
RADARR_KEY                  = None if RADARR_URL == None else \
                              get_config_value('RADARR_KEY',                    'radarr',       True,   str)

# Sonarr    
SONARR_URL                  = get_config_value('SONARR_URL',                    'sonarr',       False,  str)
SONARR_KEY                  = None if SONARR_URL == None else \
                              get_config_value('SONARR_KEY',                    'sonarr',       True,   str)

# Lidarr    
LIDARR_URL                  = get_config_value('LIDARR_URL',                    'lidarr',       False,  str)
LIDARR_KEY                  = None if LIDARR_URL == None else \
                              get_config_value('LIDARR_KEY',                    'lidarr',       True,   str)

# qBittorrent
QBITTORRENT_URL             = get_config_value('QBITTORRENT_URL',               'qbittorrent',  False,  str,    '')
QBITTORRENT_USERNAME        = get_config_value('QBITTORRENT_USERNAME',          'qbittorrent',  False,  str,    '')
QBITTORRENT_PASSWORD        = get_config_value('QBITTORRENT_PASSWORD',          'qbittorrent',  False,  str,    '')

########################################################################################################################
########### Validate settings
if not (RADARR_URL or SONARR_URL or LIDARR_URL):
    print(f'[ ERROR ]: No Radarr/Sonarr/Lidarr URLs specified (nothing to monitor)')
    sys.exit(0)

########### Enrich setting variables
if RADARR_URL:      RADARR_URL      += '/api/v3'
if SONARR_URL:      SONARR_URL      += '/api/v3'
if LIDARR_URL:      LIDARR_URL      += '/api/v1'
if QBITTORRENT_URL: QBITTORRENT_URL += '/api/v2'

########### Add Variables to Dictionary
settings_dict = {}
for var_name in dir():
    if var_name.isupper():
        settings_dict[var_name] = locals()[var_name]

