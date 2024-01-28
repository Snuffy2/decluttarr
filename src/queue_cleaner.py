# Cleans the download queue
import logging, verboselogs
logger = verboselogs.VerboseLogger(__name__)
from src.utils.rest import (rest_get, rest_delete, rest_post)
import json
from src.utils.nest_functions import (add_keys_nested_dict, nested_get)
import sys, os

download_sizes = {}

class Deleted_Downloads:
    # Keeps track of which downloads have already been deleted (to not double-delete)
    def __init__(self, dict):
        self.dict = dict

async def get_queue(BASE_URL, API_KEY, params = {}):
    await rest_post(url=BASE_URL+'/command', json={'name': 'RefreshMonitoredDownloads'}, headers={'X-Api-Key': API_KEY})
    totalRecords = (await rest_get(f'{BASE_URL}/queue', API_KEY, params))['totalRecords']
    if totalRecords == 0:
        return None
    queue = await rest_get(f'{BASE_URL}/queue', API_KEY, {'page': '1', 'pageSize': totalRecords}|params) 
    return queue

async def remove_failed(settings_dict, BASE_URL, API_KEY, deleted_downloads):
    # Detects failed and triggers delete. Does not add to blocklist
    queue = await get_queue(BASE_URL, API_KEY)
    if not queue: return 0
    failedItems = []    
    for queueItem in queue['records']:
        if 'errorMessage' in queueItem and 'status' in queueItem:
            if  queueItem['status']       == 'failed' or \
               (queueItem['status']       == 'warning' and queueItem['errorMessage'] == 'The download is missing files'):
                await remove_download(BASE_URL, API_KEY, queueItem['id'], queueItem['title'], queueItem['downloadId'], 'failed', False, deleted_downloads, settings_dict['TEST_RUN'])
                failedItems.append(queueItem)
    return len(failedItems)

async def remove_stalled(settings_dict, BASE_URL, API_KEY, deleted_downloads, defective_tracker):
    # Detects stalled and triggers repeat check and subsequent delete. Adds to blocklist   
    queue = await get_queue(BASE_URL, API_KEY)
    if not queue: return 0    
    logger.debug('remove_stalled/queue: %s', str(queue))
    if settings_dict['QBITTORRENT_URL']:
        protected_dowloadItems = await rest_get(settings_dict['QBITTORRENT_URL']+'/torrents/info',params={'tag': settings_dict['NO_STALLED_REMOVAL_QBIT_TAG']}, cookies=settings_dict['QBIT_COOKIE']  )
        protected_downloadIDs = [str.upper(item['hash']) for item in protected_dowloadItems]
    else:
        protected_downloadIDs = []
    stalledItems = []    
    already_detected = []
    for queueItem in queue['records']:
        if 'errorMessage' in queueItem and 'status' in queueItem:
            if  queueItem['status']        == 'warning' and \
                queueItem['errorMessage']  == 'The download is stalled with no connections':
                    if queueItem['downloadId'] in protected_downloadIDs:
                        if queueItem['downloadId'] not in already_detected:
                            already_detected.append(queueItem['downloadId'])
                            logger.verbose('>>> Detected stalled download, tagged not to be killed: %s',queueItem['title'])
                    else:
                        stalledItems.append(queueItem)
    await check_permitted_attempts(settings_dict, stalledItems, 'stalled', True, deleted_downloads, BASE_URL, API_KEY, defective_tracker)
    queue = await get_queue(BASE_URL, API_KEY) 
    logger.debug('remove_stalled/queue OUT: %s', str(queue))
    return len(stalledItems)

async def test_remove_ALL(settings_dict, BASE_URL, API_KEY, deleted_downloads, defective_tracker):
    # Detects stalled and triggers repeat check and subsequent delete. Adds to blocklist   
    queue = await get_queue(BASE_URL, API_KEY)
    if not queue: return 0    
    logger.debug('test_remove_ALL/queue: %s', str(queue))
    stalledItems = []    
    for queueItem in queue['records']:
        stalledItems.append(queueItem)
    await check_permitted_attempts(settings_dict, stalledItems, 'stalled', True, deleted_downloads, BASE_URL, API_KEY, defective_tracker)
    logger.debug('test_remove_ALL/queue OUT: %s', str(await get_queue(BASE_URL, API_KEY) ))
    return len(stalledItems)


async def remove_metadata_missing(settings_dict, BASE_URL, API_KEY, deleted_downloads, defective_tracker):
    # Detects downloads stuck downloading meta data and triggers repeat check and subsequent delete. Adds to blocklist  
    queue = await get_queue(BASE_URL, API_KEY)
    if not queue: return 0    
    logger.debug('remove_metadata_missing/queue: %s', str(queue))
    missing_metadataItems = []
    for queueItem in queue['records']:
        if 'errorMessage' in queueItem and 'status' in queueItem:
            if  queueItem['status']        == 'queued' and \
                queueItem['errorMessage']  == 'qBittorrent is downloading metadata':
                    missing_metadataItems.append(queueItem)
    await check_permitted_attempts(settings_dict, missing_metadataItems, 'missing metadata', True, deleted_downloads, BASE_URL, API_KEY, defective_tracker)
    logger.debug('remove_metadata_missing/queue OUT: %s', str(await get_queue(BASE_URL, API_KEY) ))
    return len(missing_metadataItems)

async def remove_orphans(settings_dict, BASE_URL, API_KEY, deleted_downloads, full_queue_param):
    # Removes downloads belonging to movies/tv shows that have been deleted in the meantime
    full_queue = await get_queue(BASE_URL, API_KEY, params = {full_queue_param: True})
    if not full_queue: return 0 # By now the queue may be empty 
    queue = await get_queue(BASE_URL, API_KEY) 
    logger.debug('remove_orphans/full queue IN: %s', str(full_queue))
    logger.debug('remove_orphans/queue IN: %s', str(queue))
    full_queue_items = [{'id': queueItem['id'], 'title': queueItem['title'], 'downloadId': queueItem['downloadId']} for queueItem in full_queue['records']]
    if queue:
        queue_ids = [queueItem['id'] for queueItem in queue['records']]
    else:
        queue_ids = []
    orphanItems = [{'id': queueItem['id'], 'title': queueItem['title'], 'downloadId': queueItem['downloadId']} for queueItem in full_queue_items if queueItem['id'] not in queue_ids]
    for queueItem in orphanItems:
        await remove_download(settings_dict, BASE_URL, API_KEY, queueItem['id'], queueItem['title'], queueItem['downloadId'], 'orphan', False, deleted_downloads)
    logger.debug('remove_orphans/full queue OUT: %s', str(await get_queue(BASE_URL, API_KEY, params = {full_queue_param: True})))
    logger.debug('remove_orphans/queue OUT: %s', str(await get_queue(BASE_URL, API_KEY) ))
    return len(orphanItems)

async def remove_unmonitored(settings_dict, BASE_URL, API_KEY, deleted_downloads, arr_type):
    # Removes downloads belonging to movies/tv shows that are not monitored
    queue = await get_queue(BASE_URL, API_KEY) 
    if not queue: return 0
    logger.debug('remove_unmonitored/queue IN: %s', str(queue))
    downloadItems = []
    if settings_dict['QBITTORRENT_URL']:
        protected_dowloadItems = await rest_get(settings_dict['QBITTORRENT_URL']+'/torrents/info',params={'tag': settings_dict['NO_STALLED_REMOVAL_QBIT_TAG']}, cookies=settings_dict['QBIT_COOKIE']  )
        protected_downloadIDs = [str.upper(item['hash']) for item in protected_dowloadItems]
    else:
        protected_downloadIDs = []
    for queueItem in queue['records']:
        if arr_type == 'sonarr': 
            monitored = (await rest_get(f'{BASE_URL}/episode/{str(queueItem["episodeId"])}', API_KEY))['monitored']
        elif arr_type == 'radarr': 
            monitored = (await rest_get(f'{BASE_URL}/movie/{str(queueItem["movieId"])}', API_KEY))['monitored']
        elif arr_type == 'lidarr': 
            monitored = (await rest_get(f'{BASE_URL}/album/{str(queueItem["albumId"])}', API_KEY))['monitored']            
        downloadItems.append({'downloadId': queueItem['downloadId'], 'id': queueItem['id'], 'monitored': monitored, 'title': queueItem['title']})
    unmonitoredItems= []
    already_detected = []
    for downloadItem in downloadItems:
        if not downloadItem['monitored']:
            if downloadItem['downloadId'] in protected_downloadIDs:
                if downloadItem['downloadId'] not in already_detected:
                    already_detected.append(queueItem['downloadId'])
                    logger.verbose('>>> Detected unmonitored download, tagged not to be killed: %s',downloadItem['title'])
            else:
                unmonitoredItems.append(downloadItem)

    for queueItem in unmonitoredItems:
        await remove_download(settings_dict, BASE_URL, API_KEY, queueItem['id'], queueItem['title'], queueItem['downloadId'], 'unmonitored', False, deleted_downloads)
    logger.debug('remove_unmonitored/queue OUT: %s', str(await get_queue(BASE_URL, API_KEY) ))
    return len(unmonitoredItems)

async def remove_slow(settings_dict, BASE_URL, API_KEY, deleted_downloads, defective_tracker, download_sizes):
    # Detects slow downloads and triggers delete. Adds to blocklist
    queue = await get_queue(BASE_URL, API_KEY)
    if not queue: return 0
    logger.debug('remove_slow/queue: %s', str(queue))
    if settings_dict['QBITTORRENT_URL']:
        protected_dowloadItems = await rest_get(settings_dict['QBITTORRENT_URL']+'/torrents/info',params={'tag': settings_dict['NO_SLOW_REMOVAL_QBIT_TAG']}, cookies=settings_dict['QBIT_COOKIE']  )
        protected_downloadIDs = [str.upper(item['hash']) for item in protected_dowloadItems]
    else:
        protected_downloadIDs = []
    slowItems = []   
    already_detected = []
    
    for queueItem in queue['records']:
        if 'downloadId' in queueItem and 'size' in queueItem and 'sizeleft' in queueItem and 'status' in queueItem:
            downloaded_size = int((queueItem['size'] - queueItem['sizeleft']) / 1000)
            speed = (downloaded_size - download_sizes[queueItem['downloadId']]) / (settings_dict['REMOVE_TIMER'] * 60)
            if  queueItem['status'] == 'downloading' and \
                queueItem['downloadId'] in download_sizes and \
                speed < settings_dict['MIN_DOWNLOAD_SPEED']:
                    if queueItem['downloadId'] in protected_downloadIDs:
                        if queueItem['downloadId'] not in already_detected:
                            already_detected.append(queueItem['downloadId'])
                            logger.verbose('>>> Detected slow download, tagged not to be killed: %s (%dKB/s)',queueItem['title'], speed)
                    else:
                        slowItems.append(queueItem)
            try:
                logger.verbose(f'{(downloaded_size - download_sizes[queueItem["downloadId"]]) * settings_dict["REMOVE_TIMER"] / 60},  : {queueItem["title"]}')
            except: pass
            download_sizes[queueItem['downloadId']] = downloaded_size
    await check_permitted_attempts(settings_dict, slowItems, 'slow', True, deleted_downloads, BASE_URL, API_KEY, defective_tracker)
    queue = await get_queue(BASE_URL, API_KEY) 
    logger.debug('remove_slow/queue OUT: %s', str(queue))
    return len(slowItems)

async def check_permitted_attempts(settings_dict, current_defective_items, failType, blocklist, deleted_downloads, BASE_URL, API_KEY, defective_tracker):
    # Checks if downloads are repeatedly found as stalled / stuck in metadata and if yes, deletes them
    # 1. Create list of currently defective
    current_defective = {}
    for queueItem in current_defective_items:
        current_defective[queueItem['id']] = {'title': queueItem['title'],'downloadId': queueItem['downloadId']}
    logger.debug('check_permitted_attempts/current_defective: %s', str(current_defective))
    # 2. Check if those that were previously defective are no longer defective -> those are recovered
    try:
        recovered_ids = [tracked_id for tracked_id in defective_tracker.dict[BASE_URL][failType] if tracked_id not in current_defective]
    except KeyError:
        recovered_ids = []
    logger.debug('check_permitted_attempts/recovered_ids: %s' + str(recovered_ids))
    for recovered_id in recovered_ids:
       del defective_tracker.dict[BASE_URL][failType][recovered_id]
    logger.debug('check_permitted_attempts/defective_tracker.dict IN: %s', str(defective_tracker.dict))
    # 3. For those that are defective, add attempt + 1 if present before, or make attempt = 0. If exceeding number of permitted attempts, delete hem
    download_ids_stuck = []
    for queueId in current_defective:
        try: 
            defective_tracker.dict[BASE_URL][failType][queueId]['Attempts'] += 1
        except KeyError:
            await add_keys_nested_dict(defective_tracker.dict,[BASE_URL, failType, queueId], {'title': current_defective[queueId]['title'], 'downloadId': current_defective[queueId]['downloadId'], 'Attempts': 1})
        if current_defective[queueId]['downloadId'] not in download_ids_stuck:
            download_ids_stuck.append(current_defective[queueId]['downloadId'])
            logger.info('>>> Detected %s download (%s out of %s permitted times): %s', failType, str(defective_tracker.dict[BASE_URL][failType][queueId]['Attempts']), str(settings_dict['PERMITTED_ATTEMPTS']), defective_tracker.dict[BASE_URL][failType][queueId]['title'])
        if defective_tracker.dict[BASE_URL][failType][queueId]['Attempts'] > settings_dict['PERMITTED_ATTEMPTS']:
            await remove_download(settings_dict, BASE_URL, API_KEY, queueId, current_defective[queueId]['title'], current_defective[queueId]['downloadId'],  failType, blocklist, deleted_downloads)
    logger.debug('check_permitted_attempts/defective_tracker.dict OUT: %s', str(defective_tracker.dict))
    return

async def remove_download(settings_dict, BASE_URL, API_KEY, queueId, queueTitle, downloadId, failType, blocklist, deleted_downloads):
    # Removes downloads and creates log entry
    logger.debug('remove_download/deleted_downloads.dict IN: %s' + str(deleted_downloads.dict)) 
    if downloadId not in deleted_downloads.dict:
        logger.info('>>> Removing %s download: %s', failType, queueTitle)
        if not settings_dict['TEST_RUN']: await rest_delete(f'{BASE_URL}/queue/{queueId}', API_KEY, {'removeFromClient': True, 'blocklist': blocklist}) 
        deleted_downloads.dict.append(downloadId)   
    
    logger.debug('remove_download/deleted_downloads.dict OUT: %s' + str(deleted_downloads.dict)) 
    return

########### MAIN FUNCTION ###########
async def queue_cleaner(settings_dict, arr_type, defective_tracker):
    # Read out correct instance depending on radarr/sonarr flag
    run_dict = {}
    if arr_type == 'radarr':
        BASE_URL    = settings_dict['RADARR_URL']
        API_KEY     = settings_dict['RADARR_KEY']
        NAME        = settings_dict['RADARR_NAME']
        full_queue_param = 'includeUnknownMovieItems'
    elif arr_type == 'sonarr':
        BASE_URL    = settings_dict['SONARR_URL']
        API_KEY     = settings_dict['SONARR_KEY']
        NAME        = settings_dict['SONARR_NAME']
        full_queue_param = 'includeUnknownSeriesItems'
    elif arr_type == 'lidarr':
        BASE_URL    = settings_dict['LIDARR_URL']
        API_KEY     = settings_dict['LIDARR_KEY']
        NAME        = settings_dict['LIDARR_NAME']
        full_queue_param = 'includeUnknownArtistItems'
    else:
        logger.error('Unknown arr_type specified, exiting: %s', str(arr_type))
        sys.exit()
        
    # Cleans up the downloads queue
    logger.verbose('Cleaning queue on %s:', NAME)
    try:
        
        full_queue = await get_queue(BASE_URL, API_KEY, params = {full_queue_param: True})
        if not full_queue: 
            logger.verbose('>>> Queue is empty.')
            return
              
        deleted_downloads = Deleted_Downloads([])
        items_detected = 0

        #items_detected += await test_remove_ALL(             settings_dict, BASE_URL, API_KEY, deleted_downloads, defective_tracker)
        
        global download_sizes
        if settings_dict['MIN_DOWNLOAD_SPEED'] > 0:
            items_detected += await remove_slow(              settings_dict, BASE_URL, API_KEY, deleted_downloads, defective_tracker, download_sizes)
            
        if settings_dict['REMOVE_FAILED']:
            items_detected += await remove_failed(            settings_dict, BASE_URL, API_KEY, deleted_downloads)
        
        if settings_dict['REMOVE_STALLED']: 
            items_detected += await remove_stalled(           settings_dict, BASE_URL, API_KEY, deleted_downloads, defective_tracker)

        if settings_dict['REMOVE_METADATA_MISSING']: 
            items_detected += await remove_metadata_missing(  settings_dict, BASE_URL, API_KEY, deleted_downloads, defective_tracker)

        if settings_dict['REMOVE_ORPHANS']: 
            items_detected += await remove_orphans(           settings_dict, BASE_URL, API_KEY, deleted_downloads, full_queue_param)

        if settings_dict['REMOVE_UNMONITORED']: 
            items_detected += await remove_unmonitored(       settings_dict, BASE_URL, API_KEY, deleted_downloads, arr_type)

        if items_detected == 0:
            logger.verbose('>>> Queue is clean.')
    except Exception as error:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.warning('>>> Queue cleaning failed on %s. (File: %s / Line: %s / Error Message: %s / Error Type: %s)', NAME, fname, exc_tb.tb_lineno, error, exc_type)



