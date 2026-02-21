from flask import make_response
from flask_restful import Api
from werkzeug.wrappers import Response



from redash.handlers.alerts import (AlertListResource, AlertResource,
                                    AlertSubscriptionListResource,
                                    AlertSubscriptionResource)
from redash.handlers.base import org_scoped_rule
from redash.handlers.table_scopes import (TableScopeListResource,
                                          TableScopeQueryResource,
                                          TableScopeFilterResource,
                                          TableScopeResource)
from redash.handlers.column_layouts import ColumnLayoutListResource                                          
from redash.handlers.dashboards import (DashboardFavoriteListResource,
                                        DashboardListResource,
                                        DashboardResource,
                                        DashboardShareResource,
                                        DashboardTagsResource,
                                        PublicDashboardResource,
                                        DashboardProjectResource,
                                        ProjectDashboardCreateResource,
                                        DashboardDeleteResource)
from redash.handlers.data_sources import (DataSourceListResource,
                                          DataSourcePauseResource,
                                          DataSourceResource,
                                          DataSourcePreviewResource,
                                          DataSourceSchemaResource,
                                          DataSourceTestResource,
                                          DataSourceTypeListResource,
                                          PrivateDataSourceListResource,
                                          SharedDataSourceListResource,
                                          EnterpriseDataSourceListResource,
                                          DataSourceQueriesResource)
from redash.handlers.destinations import (DestinationListResource,
                                          DestinationResource,
                                          DestinationTypeListResource)
from redash.handlers.events import EventsResource
from redash.handlers.favorites import (DashboardFavoriteResource,
                                       QueryFavoriteResource)
from redash.handlers.groups import (GroupDataSourceListResource,
                                    GroupDataSourceResource, GroupListResource,
                                    GroupMemberListResource,
                                    GroupMemberResource, GroupResource,
                                    SharedGroupListResource)

from redash.handlers.data_source_approval import (DataSourceApprovalListResource,
                                                  DataSourceApprovalUpdateResource)

from redash.handlers.my_approvals import (MyApprovalsResource, 
                                          MyRequestsResource)

from redash.handlers.organization_vdb import (OrganizationVDBResource,
                                              VDBCredentialRotationResource,
                                              VDBHealthCheckResource)

from redash.handlers.user_vdb import (UserVDBResource,
                                      UserVDBRedeployResource)

from redash.handlers.shared_vdb import (SharedVDBResource,
                                        SharedVDBRedeployResource)

from redash.handlers.vdb_health import (UserVDBHealthResource,
                                        SharedVDBHealthResource,
                                        OrganizationVDBsHealthResource)

from redash.handlers.project_sharing_handler import (ProjectSharingResource,
                                                     ProjectUnsharingResource)                                                  

from redash.handlers.projects import (ProjectListResource,
                                    ProjectResource,
                                    ProjectMigrationStatusResource,
                                    ProjectMembersResource,
                                    ProjectUnshareImpactResource,
                                    ProjectMemberRoleResource,
                                    ProjectDataSourcesResource,
                                    ProjectDataSourceResource,
                                    PrivateProjectListResource,
                                    PublicProjectListResource,
                                    ProjectItemsResource,
                                    ProjectQueriesWithFieldsResource,
                                    CombinePublicAndPrivateProjectListResource,
                                    ProjectRenameResource)
                        
from redash.handlers.permissions import (CheckPermissionResource,
                                         ObjectPermissionsListResource,
                                         PermissionCheckResource)
from redash.handlers.roles import (RolesListResource,
                                   UserRolesResource,
                                   UserRoleResource,
                                   ProjectAdminsResource)
from redash.handlers.queries import (MyQueriesResource, QueryArchiveResource,
                                     QueryFavoriteListResource,
                                     QueryForkResource, QueryListResource,
                                     QueryRecentResource, QueryRefreshResource,
                                     QueryResource, QuerySearchResource,
                                     QueryTagsResource,
                                     QueryRegenerateApiKeyResource,
                                     QueryProjectResource,
                                     MyUnassignedQueryListResource,
                                    ProjectAvailableQueriesResource,
                                    QueryDeleteResource)
from redash.handlers.query_results import (JobResource,
                                           QueryResultDropdownResource,
                                           QueryDropdownsResource,
                                           QueryResultListResource,
                                           QueryResultResource)
from redash.handlers.query_snippets import (QuerySnippetListResource,
                                            QuerySnippetResource)
from redash.handlers.settings import OrganizationSettings
from redash.handlers.users import (UserDisableResource, UserInviteResource,
                                   UserListResource,
                                   UserRegenerateApiKeyResource,
                                   UserResetPasswordResource, UserResource,
                                   UserMFAResource)
from redash.handlers.mfa import (MFAVerifyResource, MFAResendResource,
                                 MFAEnrollResource, MFAEnrollVerifyResource,
                                 MFAEnrollStatusResource, MFASettingsResource,
                                 MFABackupCodesResource)
from redash.handlers.visualizations import (VisualizationListResource,
                                            VisualizationResource)
from redash.handlers.widgets import WidgetListResource, WidgetResource
from redash.utils import json_dumps


class ApiExt(Api):
    def add_org_resource(self, resource, *urls, **kwargs):
        urls = [org_scoped_rule(url) for url in urls]
        return self.add_resource(resource, *urls, **kwargs)


api = ApiExt()


@api.representation('application/json')
def json_representation(data, code, headers=None):
    # Flask-Restful checks only for flask.Response but flask-login uses werkzeug.wrappers.Response
    if isinstance(data, Response):
        return data
    resp = make_response(json_dumps(data), code)
    resp.headers.extend(headers or {})
    return resp


api.add_org_resource(AlertResource, '/api/alerts/<alert_id>', endpoint='alert')
api.add_org_resource(AlertSubscriptionListResource, '/api/alerts/<alert_id>/subscriptions', endpoint='alert_subscriptions')
api.add_org_resource(AlertSubscriptionResource, '/api/alerts/<alert_id>/subscriptions/<subscriber_id>', endpoint='alert_subscription')
api.add_org_resource(AlertListResource, '/api/alerts', endpoint='alerts')

api.add_org_resource(DashboardListResource, '/api/dashboards', endpoint='dashboards')
api.add_org_resource(DashboardResource, '/api/dashboards/<dashboard_slug>', endpoint='dashboard')
api.add_org_resource(PublicDashboardResource, '/api/dashboards/public/<token>', endpoint='public_dashboard')
api.add_org_resource(DashboardShareResource, '/api/dashboards/<dashboard_id>/share', endpoint='dashboard_share')
api.add_org_resource(DashboardProjectResource, '/api/dashboards/<int:dashboard_id>', endpoint='dashboard_projects')
api.add_org_resource(ProjectDashboardCreateResource, '/api/projects/<int:project_id>/dashboards', endpoint='project_dashboards')
api.add_org_resource(DashboardDeleteResource, '/api/dashboards/<int:dashboard_id>/delete', endpoint='dashboard_delete')

api.add_org_resource(DataSourceTypeListResource, '/api/data_sources/types', endpoint='data_source_types')
api.add_org_resource(DataSourceListResource, '/api/data_sources', endpoint='data_sources')
api.add_org_resource(DataSourceSchemaResource, '/api/data_sources/<data_source_id>/schema')
api.add_org_resource(DataSourcePauseResource, '/api/data_sources/<data_source_id>/pause')
api.add_org_resource(DataSourceTestResource, '/api/data_sources/<data_source_id>/test')
api.add_org_resource(DataSourcePreviewResource, '/api/data_sources/<data_source_id>/preview', endpoint='data_source_preview')
api.add_org_resource(DataSourceResource, '/api/data_sources/<data_source_id>', endpoint='data_source')
api.add_org_resource(DataSourceQueriesResource, '/api/data_sources/<data_source_id>/queries', endpoint='data_source_queries')
api.add_org_resource(PrivateDataSourceListResource, '/api/private_data_sources', endpoint='private_data_sources')
api.add_org_resource(SharedDataSourceListResource, '/api/shared_data_sources', endpoint='shared_data_sources')
api.add_org_resource(EnterpriseDataSourceListResource, '/api/enterprise_data_sources', endpoint='enterprise_data_sources')

# VDB Multi-Tenancy API endpoints
api.add_org_resource(OrganizationVDBResource, '/api/organizations/<int:org_id>/vdb', endpoint='organization_vdb')
api.add_org_resource(VDBCredentialRotationResource, '/api/organizations/<int:org_id>/vdb/rotate-credentials', endpoint='vdb_rotate_credentials')
api.add_org_resource(VDBHealthCheckResource, '/api/organizations/<int:org_id>/vdb/health', endpoint='vdb_health_check')
api.add_org_resource(VDBHealthCheckResource, '/api/vdbs/health', endpoint='vdb_bulk_health_check')

# User-Level VDB Isolation API endpoints
# User VDB management
api.add_org_resource(UserVDBResource, '/api/users/<int:user_id>/vdb', endpoint='user_vdb')
api.add_org_resource(UserVDBRedeployResource, '/api/users/<int:user_id>/vdb/redeploy', endpoint='user_vdb_redeploy')

# Shared VDB management
api.add_org_resource(SharedVDBResource, '/api/shared_vdb', endpoint='shared_vdb_current_org')
api.add_org_resource(SharedVDBResource, '/api/organizations/<int:org_id>/shared_vdb', endpoint='shared_vdb')
api.add_org_resource(SharedVDBRedeployResource, '/api/shared_vdb/redeploy', endpoint='shared_vdb_redeploy_current_org')
api.add_org_resource(SharedVDBRedeployResource, '/api/organizations/<int:org_id>/shared_vdb/redeploy', endpoint='shared_vdb_redeploy')

# VDB health check endpoints
api.add_org_resource(UserVDBHealthResource, '/api/users/<int:user_id>/vdb/health', endpoint='user_vdb_health')
api.add_org_resource(SharedVDBHealthResource, '/api/shared_vdb/health', endpoint='shared_vdb_health_current_org')
api.add_org_resource(SharedVDBHealthResource, '/api/organizations/<int:org_id>/shared_vdb/health', endpoint='shared_vdb_health')
api.add_org_resource(OrganizationVDBsHealthResource, '/api/vdbs/health/all', endpoint='org_vdbs_health_current_org')
api.add_org_resource(OrganizationVDBsHealthResource, '/api/organizations/<int:org_id>/vdbs/health/all', endpoint='org_vdbs_health')

# Project sharing endpoints
api.add_org_resource(ProjectSharingResource, '/api/projects/<int:project_id>/share', endpoint='project_share')
api.add_org_resource(ProjectUnsharingResource, '/api/projects/<int:project_id>/unshare', endpoint='project_unshare')

api.add_org_resource(GroupListResource, '/api/groups', endpoint='groups')
api.add_org_resource(GroupResource, '/api/groups/<group_id>', endpoint='group')
api.add_org_resource(GroupMemberListResource, '/api/groups/<group_id>/members', endpoint='group_members')
api.add_org_resource(GroupMemberResource, '/api/groups/<group_id>/members/<user_id>', endpoint='group_member')
api.add_org_resource(GroupDataSourceListResource, '/api/groups/<group_id>/data_sources', endpoint='group_data_sources')
api.add_org_resource(GroupDataSourceResource, '/api/groups/<group_id>/data_sources/<data_source_id>', endpoint='group_data_source')
api.add_org_resource(SharedGroupListResource, '/api/shared_groups', endpoint='shared_groups')


api.add_org_resource(ProjectListResource, '/api/projects', endpoint='projects')
api.add_org_resource(ProjectResource, '/api/projects/<project_id>', endpoint='project')
api.add_org_resource(ProjectMigrationStatusResource, '/api/projects/<project_id>/migration/status', endpoint='project_migration_status')
api.add_org_resource(ProjectMembersResource, '/api/projects/<project_id>/members', endpoint='project_members')
api.add_org_resource(ProjectMembersResource, '/api/projects/<project_id>/members/<user_id>', endpoint='project_member')
api.add_org_resource(ProjectUnshareImpactResource, '/api/projects/<project_id>/unshare/impact', endpoint='project_unshare_impact')
api.add_org_resource(ProjectMemberRoleResource, '/api/projects/<project_id>/members/<user_id>/role', endpoint='project_member_role')
api.add_org_resource(ProjectDataSourcesResource, '/api/projects/<project_id>/data_sources', endpoint='project_data_sources')
api.add_org_resource(ProjectDataSourceResource, '/api/projects/<project_id>/data_sources/<data_source_id>', endpoint='data_source_approval_update')
api.add_org_resource(PrivateProjectListResource, '/api/private_projects', endpoint='private_projects')
api.add_org_resource(PublicProjectListResource, '/api/public_projects', endpoint='public_projects')
api.add_org_resource(ProjectItemsResource, '/api/projects/<project_id>/items', endpoint='project_items')
api.add_org_resource(ProjectQueriesWithFieldsResource, '/api/projects/<project_id>/queries_with_field', endpoint='project_queries_with_fields',)
api.add_org_resource(CombinePublicAndPrivateProjectListResource, '/api/available_projects', endpoint='available_projects')
api.add_org_resource(ProjectRenameResource, '/api/projects/<int:project_id>/rename', endpoint='project_rename')

api.add_org_resource(DataSourceApprovalListResource, '/api/data_source_approval', endpoint='data_source_approval_list')
api.add_org_resource(DataSourceApprovalUpdateResource, '/api/approvals/<int:approval_id>/update', endpoint='approval_update')
api.add_org_resource(MyApprovalsResource, '/api/my_approvals', endpoint='my_approvals')
api.add_org_resource(MyRequestsResource, '/api/my_requests', endpoint='my_requests')

api.add_org_resource(QueryFavoriteListResource, '/api/queries/favorites', endpoint='query_favorites')
api.add_org_resource(QueryFavoriteResource, '/api/queries/<query_id>/favorite', endpoint='query_favorite')
api.add_org_resource(DashboardFavoriteListResource, '/api/dashboards/favorites', endpoint='dashboard_favorites')
api.add_org_resource(DashboardFavoriteResource, '/api/dashboards/<object_id>/favorite', endpoint='dashboard_favorite')

api.add_org_resource(QueryTagsResource, '/api/queries/tags', endpoint='query_tags')
api.add_org_resource(DashboardTagsResource, '/api/dashboards/tags', endpoint='dashboard_tags')

api.add_org_resource(QuerySearchResource, '/api/queries/search', endpoint='queries_search')
api.add_org_resource(QueryRecentResource, '/api/queries/recent', endpoint='recent_queries')
api.add_org_resource(QueryArchiveResource, '/api/queries/archive', endpoint='queries_archive')
api.add_org_resource(QueryListResource, '/api/queries', endpoint='queries')
api.add_org_resource(MyQueriesResource, '/api/queries/my', endpoint='my_queries')
api.add_org_resource(QueryRefreshResource, '/api/queries/<query_id>/refresh', endpoint='query_refresh')
api.add_org_resource(QueryResource, '/api/queries/<query_id>', endpoint='query')
api.add_org_resource(QueryForkResource, '/api/queries/<query_id>/fork', endpoint='query_fork')
api.add_org_resource(QueryDeleteResource, '/api/queries/<int:query_id>/delete', endpoint='query_delete')
api.add_org_resource(MyUnassignedQueryListResource, '/api/my_unassigned_queries', endpoint='my_unassigned_queries')
api.add_org_resource(ProjectAvailableQueriesResource, '/api/projects/<int:project_id>/available_queries', endpoint='project_available_queries')

api.add_org_resource(QueryRegenerateApiKeyResource,
                     '/api/queries/<query_id>/regenerate_api_key',
                     endpoint='query_regenerate_api_key')
api.add_org_resource(QueryProjectResource, '/api/queries/<query_id>/projects', endpoint='query_projects')

api.add_org_resource(ObjectPermissionsListResource, '/api/<object_type>/<object_id>/acl', endpoint='object_permissions')
api.add_org_resource(CheckPermissionResource, '/api/<object_type>/<object_id>/acl/<access_type>', endpoint='check_permissions')

# RBAC Permission Checking Endpoint
api.add_org_resource(PermissionCheckResource, '/api/permissions/check', endpoint='permission_check')

# RBAC Role Management Endpoints
api.add_org_resource(RolesListResource, '/api/roles', endpoint='roles')
api.add_org_resource(UserRolesResource, '/api/users/<int:user_id>/roles', endpoint='user_roles')
api.add_org_resource(UserRoleResource, '/api/users/<int:user_id>/roles/<int:role_id>', endpoint='user_role')
api.add_org_resource(ProjectAdminsResource, '/api/projects/<int:project_id>/admins', endpoint='project_admins')

api.add_org_resource(QueryResultListResource, '/api/query_results', endpoint='query_results')
api.add_org_resource(QueryResultDropdownResource, '/api/queries/<query_id>/dropdown', endpoint='query_result_dropdown')
api.add_org_resource(QueryDropdownsResource, '/api/queries/<query_id>/dropdowns/<dropdown_query_id>', endpoint='query_result_dropdowns')
api.add_org_resource(QueryResultResource,
                     '/api/query_results/<query_result_id>.<filetype>',
                     '/api/query_results/<query_result_id>',
                     '/api/queries/<query_id>/results',
                     '/api/queries/<query_id>/results.<filetype>',
                     '/api/queries/<query_id>/results/<query_result_id>.<filetype>',
                     endpoint='query_result')
api.add_org_resource(JobResource,
                     '/api/jobs/<job_id>',
                     '/api/queries/<query_id>/jobs/<job_id>',
                     endpoint='job')

api.add_org_resource(TableScopeListResource, '/api/scopes', endpoint='table_scope_list')
api.add_org_resource(TableScopeQueryResource, '/api/scopes/by-query/<int:query_id>', endpoint='table_scope_query')
api.add_org_resource(TableScopeFilterResource,'/api/scopes/filter', endpoint='table_scope_filter')
api.add_org_resource(TableScopeResource, '/api/scopes/<int:scope_id>', endpoint='table_scope_resource')
api.add_org_resource(ColumnLayoutListResource, '/api/column_layouts', endpoint='column_layouts')
api.add_org_resource(UserListResource, '/api/users', endpoint='users')
api.add_org_resource(UserResource, '/api/users/<user_id>', endpoint='user')
api.add_org_resource(UserInviteResource, '/api/users/<user_id>/invite', endpoint='user_invite')
api.add_org_resource(UserResetPasswordResource, '/api/users/<user_id>/reset_password', endpoint='user_reset_password')
api.add_org_resource(UserRegenerateApiKeyResource,
                     '/api/users/<user_id>/regenerate_api_key',
                     endpoint='user_regenerate_api_key')
api.add_org_resource(UserDisableResource, '/api/users/<user_id>/disable', endpoint='user_disable')
api.add_org_resource(UserMFAResource, '/api/users/<user_id>/mfa', endpoint='user_mfa')

api.add_org_resource(VisualizationListResource, '/api/visualizations', endpoint='visualizations')
api.add_org_resource(VisualizationResource, '/api/visualizations/<visualization_id>', endpoint='visualization')

api.add_org_resource(WidgetListResource, '/api/widgets', endpoint='widgets')
api.add_org_resource(WidgetResource, '/api/widgets/<int:widget_id>', endpoint='widget')

api.add_org_resource(DestinationTypeListResource, '/api/destinations/types', endpoint='destination_types')
api.add_org_resource(DestinationResource, '/api/destinations/<destination_id>', endpoint='destination')
api.add_org_resource(DestinationListResource, '/api/destinations', endpoint='destinations')

api.add_org_resource(QuerySnippetResource, '/api/query_snippets/<snippet_id>', endpoint='query_snippet')
api.add_org_resource(QuerySnippetListResource, '/api/query_snippets', endpoint='query_snippets')

api.add_org_resource(OrganizationSettings, '/api/settings/organization', endpoint='organization_settings')

# MFA (Multi-Factor Authentication) API endpoints
# Register both org-scoped and non-org-scoped routes for MFA challenge/verify
# Non-org routes are needed during login before user has org context
api.add_resource(MFAVerifyResource, '/api/auth/mfa/verify', endpoint='mfa_verify_noorg')
api.add_resource(MFAResendResource, '/api/auth/mfa/resend', endpoint='mfa_resend_noorg')
api.add_org_resource(MFAVerifyResource, '/api/auth/mfa/verify', endpoint='mfa_verify')
api.add_org_resource(MFAResendResource, '/api/auth/mfa/resend', endpoint='mfa_resend')
api.add_org_resource(MFAEnrollResource, '/api/auth/mfa/enroll', endpoint='mfa_enroll')
api.add_org_resource(MFAEnrollVerifyResource, '/api/auth/mfa/enroll/verify', endpoint='mfa_enroll_verify')
api.add_org_resource(MFAEnrollStatusResource, '/api/auth/mfa/enroll/status', endpoint='mfa_enroll_status')
api.add_org_resource(MFASettingsResource, '/api/auth/mfa/settings', endpoint='mfa_settings')
api.add_org_resource(MFABackupCodesResource, '/api/auth/mfa/backup-codes', endpoint='mfa_backup_codes')