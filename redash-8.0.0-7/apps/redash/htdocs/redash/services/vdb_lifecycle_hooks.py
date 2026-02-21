"""
VDB Lifecycle Hooks

Lifecycle hooks for automatic VDB provisioning and redeployment based on
data source and query changes. These hooks ensure that user VDBs are
automatically created and updated when users create or modify data sources
and queries.
"""

import logging
from redash import settings
from redash.models import db
from redash.models.user_vdb import UserVDB
from redash.models.shared_vdb import SharedVDB
from redash.services.vdb_management import VDBManagementService, VDBProvisioningError

logger = logging.getLogger(__name__)


def on_data_source_created(data_source):
    """
    Hook called when a data source is created.
    
    Automatically provisions user VDB when first data source is created,
    or redeploys existing user VDB to include the new data source.
    
    Args:
        data_source: DataSource instance that was created
    """
    # Check if user-level VDB isolation is enabled
    if not getattr(settings, 'USER_VDB_ISOLATION_ENABLED', False):
        logger.debug('User VDB isolation is disabled, skipping data source creation hook')
        return
    
    try:
        user_id = data_source.owner
        org_id = data_source.org_id
        
        # Skip if data source has no owner (e.g., shared data sources)
        if not user_id:
            logger.debug('[VDB_HOOK] Data source {} has no owner, skipping VDB provisioning'.format(
                data_source.id
            ))
            return
        
        logger.info('[VDB_HOOK] Data source created: id={}, name={}, user_id={}, org_id={}'.format(
            data_source.id, data_source.name, user_id, org_id
        ))
        
        # Check if user already has a VDB
        user_vdb = UserVDB.get_by_user(user_id)
        
        vdb_service = VDBManagementService()
        
        if not user_vdb:
            # Provision new user VDB
            logger.info('[VDB_HOOK] No VDB found for user {}, provisioning new VDB'.format(user_id))
            try:
                user_vdb = vdb_service.provision_user_vdb(user_id, org_id)
                db.session.commit()
                logger.info('[VDB_HOOK] Successfully provisioned user VDB {} for user {}'.format(
                    user_vdb.vdb_id, user_id
                ))
            except VDBProvisioningError as e:
                logger.error('[VDB_HOOK] Failed to provision user VDB for user {}: {}'.format(
                    user_id, str(e)
                ))
                # Don't raise - allow data source creation to succeed even if VDB provisioning fails
                # User can manually trigger VDB provisioning later
        else:
            # Redeploy existing VDB with new data source
            logger.info('[VDB_HOOK] User VDB {} exists for user {}, redeploying'.format(
                user_vdb.vdb_id, user_id
            ))
            try:
                vdb_service.redeploy_user_vdb(user_id)
                db.session.commit()
                logger.info('[VDB_HOOK] Successfully redeployed user VDB {} for user {}'.format(
                    user_vdb.vdb_id, user_id
                ))
            except VDBProvisioningError as e:
                logger.error('[VDB_HOOK] Failed to redeploy user VDB for user {}: {}'.format(
                    user_id, str(e)
                ))
                # Don't raise - allow data source creation to succeed even if redeployment fails
                
    except Exception as e:
        logger.error('[VDB_HOOK] Unexpected error in data source creation hook: {}'.format(str(e)), exc_info=True)
        # Don't raise - allow data source creation to succeed even if hook fails


def on_data_source_updated(data_source):
    """
    Hook called when a data source is updated.
    
    Triggers user VDB redeployment to reflect the updated data source configuration.
    
    Args:
        data_source: DataSource instance that was updated
    """
    # Check if user-level VDB isolation is enabled
    if not getattr(settings, 'USER_VDB_ISOLATION_ENABLED', False):
        logger.debug('User VDB isolation is disabled, skipping data source update hook')
        return
    
    try:
        user_id = data_source.owner
        
        # Skip if data source has no owner (e.g., shared data sources)
        if not user_id:
            logger.debug('[VDB_HOOK] Data source {} has no owner, skipping VDB redeployment'.format(
                data_source.id
            ))
            return
        
        logger.info('[VDB_HOOK] Data source updated: id={}, name={}, user_id={}'.format(
            data_source.id, data_source.name, user_id
        ))
        
        # Check if user has a VDB
        user_vdb = UserVDB.get_by_user(user_id)
        
        if not user_vdb:
            logger.warning('[VDB_HOOK] No VDB found for user {} during data source update'.format(user_id))
            return
        
        # Redeploy user VDB
        logger.info('[VDB_HOOK] Redeploying user VDB {} after data source update'.format(user_vdb.vdb_id))
        try:
            vdb_service = VDBManagementService()
            vdb_service.redeploy_user_vdb(user_id)
            db.session.commit()
            logger.info('[VDB_HOOK] Successfully redeployed user VDB {} for user {}'.format(
                user_vdb.vdb_id, user_id
            ))
        except VDBProvisioningError as e:
            logger.error('[VDB_HOOK] Failed to redeploy user VDB for user {}: {}'.format(
                user_id, str(e)
            ))
            # Don't raise - allow data source update to succeed even if redeployment fails
            
    except Exception as e:
        logger.error('[VDB_HOOK] Unexpected error in data source update hook: {}'.format(str(e)), exc_info=True)
        # Don't raise - allow data source update to succeed even if hook fails


def on_query_saved(query):
    """
    Hook called when a query is saved (created or updated).
    
    Triggers user VDB redeployment to include the query definition in the VDB.
    
    Args:
        query: Query instance that was saved
    """
    # Check if user-level VDB isolation is enabled
    if not getattr(settings, 'USER_VDB_ISOLATION_ENABLED', False):
        logger.debug('User VDB isolation is disabled, skipping query save hook')
        return
    
    try:
        user_id = query.user_id
        
        logger.info('[VDB_HOOK] Query saved: id={}, name={}, user_id={}'.format(
            query.id, query.name, user_id
        ))
        
        # Check if user has a VDB
        user_vdb = UserVDB.get_by_user(user_id)
        
        if not user_vdb:
            logger.warning('[VDB_HOOK] No VDB found for user {} during query save'.format(user_id))
            return
        
        # Redeploy user VDB
        logger.info('[VDB_HOOK] Redeploying user VDB {} after query save'.format(user_vdb.vdb_id))
        try:
            vdb_service = VDBManagementService()
            vdb_service.redeploy_user_vdb(user_id)
            db.session.commit()
            logger.info('[VDB_HOOK] Successfully redeployed user VDB {} for user {}'.format(
                user_vdb.vdb_id, user_id
            ))
        except VDBProvisioningError as e:
            logger.error('[VDB_HOOK] Failed to redeploy user VDB for user {}: {}'.format(
                user_id, str(e)
            ))
            # Don't raise - allow query save to succeed even if redeployment fails
            
    except Exception as e:
        logger.error('[VDB_HOOK] Unexpected error in query save hook: {}'.format(str(e)), exc_info=True)
        # Don't raise - allow query save to succeed even if hook fails


def on_user_deleted(user):
    """
    Hook called when a user is deleted.
    
    Cleans up user VDB by undeploying from Teiid server, archiving VDB files,
    and removing VDB record from database.
    
    Args:
        user: User instance that was deleted
    """
    # Check if user-level VDB isolation is enabled
    if not getattr(settings, 'USER_VDB_ISOLATION_ENABLED', False):
        logger.debug('User VDB isolation is disabled, skipping user deletion hook')
        return
    
    try:
        user_id = user.id
        org_id = user.org_id
        
        logger.info('[VDB_HOOK] User deleted: id={}, email={}, org_id={}'.format(
            user_id, user.email, org_id
        ))
        
        # Check if user has a VDB
        user_vdb = UserVDB.get_by_user(user_id)
        
        if not user_vdb:
            logger.info('[VDB_HOOK] No VDB found for user {}, nothing to clean up'.format(user_id))
            return
        
        logger.info('[VDB_HOOK] Cleaning up user VDB {} for deleted user {}'.format(
            user_vdb.vdb_id, user_id
        ))
        
        try:
            # Delete VDB from Teiid server
            vdb_service = VDBManagementService()
            result = vdb_service.delete_vdb(user_vdb.vdb_id)
            
            if result.get('success'):
                logger.info('[VDB_HOOK] Successfully deleted VDB {} from Teiid server'.format(
                    user_vdb.vdb_id
                ))
            else:
                logger.warning('[VDB_HOOK] Failed to delete VDB {} from Teiid server: {}'.format(
                    user_vdb.vdb_id, result.get('error')
                ))
            
            # Archive VDB files
            from redash.services.customer_folders import CustomerFolderService
            folder_service = CustomerFolderService()
            
            try:
                folder_service.archive_user_vdb_files(org_id, user_id)
                logger.info('[VDB_HOOK] Successfully archived VDB files for user {}'.format(user_id))
            except Exception as e:
                logger.error('[VDB_HOOK] Failed to archive VDB files for user {}: {}'.format(
                    user_id, str(e)
                ))
            
            # Delete VDB record from database
            db.session.delete(user_vdb)
            db.session.commit()
            logger.info('[VDB_HOOK] Successfully deleted UserVDB record for user {}'.format(user_id))
            
        except Exception as e:
            logger.error('[VDB_HOOK] Failed to clean up user VDB for user {}: {}'.format(
                user_id, str(e)
            ))
            # Don't raise - allow user deletion to succeed even if VDB cleanup fails
            
    except Exception as e:
        logger.error('[VDB_HOOK] Unexpected error in user deletion hook: {}'.format(str(e)), exc_info=True)
        # Don't raise - allow user deletion to succeed even if hook fails
