# Admin Organizations API Documentation

## Overview

The Admin Organizations API provides endpoints for creating and managing organizations with automatic VDB (Virtual Database) provisioning and customer folder structure creation. These endpoints are restricted to super admin users only.

## Authentication

All endpoints require:
- **Authentication**: User must be logged in
- **Authorization**: User must have super admin role (`@require_super_admin`)

## Endpoints

### 1. Create Organization

Create a new organization with automatic VDB provisioning and customer folder creation.

**Endpoint**: `POST /api/admin/organizations`

**Request Headers**:
```
Content-Type: application/json
Cookie: session=<session_token>
```

**Request Body**:
```json
{
  "name": "Development Organization",
  "slug": "development",
  "provision_vdb": true
}
```

**Request Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Organization display name |
| `slug` | string | Yes | URL-friendly identifier (lowercase, alphanumeric, hyphens) |
| `provision_vdb` | boolean | No | Whether to provision VDB (default: true) |

**Slug Validation Rules**:
- Must be 3-50 characters
- Must start with a letter
- Can contain lowercase letters, numbers, and hyphens
- Cannot contain consecutive hyphens (`--`)
- Cannot end with a hyphen
- Must be unique across all organizations

**Response** (201 Created):
```json
{
  "organization": {
    "id": 1,
    "name": "Development Organization",
    "slug": "development",
    "created_at": "2025-11-14T10:00:00Z"
  },
  "vdb_status": {
    "provisioned": true,
    "vdb_id": "vdb_development",
    "status": "active",
    "health_status": "unknown",
    "error": null
  },
  "folders_status": {
    "created": true,
    "vdb_folder": "/opt/wildfly/teiidfiles/customers/1/vdb",
    "uploads_folder": "/opt/wildfly/teiidfiles/customers/1/uploads",
    "error": null
  }
}
```

**Error Responses**:

**400 Bad Request** - Invalid slug format:
```json
{
  "error": "Slug must start with a letter and contain only lowercase letters, numbers, and hyphens"
}
```

**400 Bad Request** - Duplicate slug:
```json
{
  "error": "Organization with slug \"development\" already exists"
}
```

**500 Internal Server Error** - Creation failed:
```json
{
  "error": "Failed to create organization: <error_message>"
}
```

**What Happens**:
1. Validates slug format and uniqueness
2. Creates organization record in database
3. Creates customer folder structure:
   - `/opt/wildfly/teiidfiles/customers/<org_id>/vdb/`
   - `/opt/wildfly/teiidfiles/customers/<org_id>/uploads/`
4. Provisions VDB from template
5. Generates secure credentials
6. Deploys VDB to Teiid server
7. Stores encrypted credentials in database
8. Records audit event

**Note**: If VDB provisioning or folder creation fails, the organization is still created. The response will include error details in the respective status objects.

---

### 2. Get Organization Details

Retrieve organization details including VDB configuration.

**Endpoint**: `GET /api/admin/organizations/<org_id>`

**Request Headers**:
```
Cookie: session=<session_token>
```

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | integer | Organization ID |

**Response** (200 OK):
```json
{
  "organization": {
    "id": 1,
    "name": "Development Organization",
    "slug": "development",
    "created_at": "2025-11-14T10:00:00Z"
  },
  "vdb": {
    "id": 1,
    "organization_id": 1,
    "vdb_id": "vdb_development",
    "vdb_host": "localhost",
    "vdb_port": 31020,
    "is_active": true,
    "health_status": "healthy",
    "last_health_check": "2025-11-14T12:00:00Z",
    "created_at": "2025-11-14T10:00:00Z",
    "updated_at": "2025-11-14T12:00:00Z"
  }
}
```

**Response** (200 OK) - No VDB:
```json
{
  "organization": {
    "id": 2,
    "name": "Production Organization",
    "slug": "production",
    "created_at": "2025-11-14T10:00:00Z"
  },
  "vdb": null
}
```

**Error Responses**:

**404 Not Found**:
```json
{
  "message": "Not found"
}
```

---

### 3. Delete Organization

Delete an organization with automatic VDB cleanup and folder archiving.

**Endpoint**: `DELETE /api/admin/organizations/<org_id>`

**Request Headers**:
```
Cookie: session=<session_token>
```

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | integer | Organization ID |

**Response** (200 OK):
```json
{
  "message": "Organization deleted successfully",
  "cleanup_status": {
    "vdb_deleted": true,
    "folders_archived": true,
    "organization_deleted": true,
    "errors": []
  }
}
```

**Response** (200 OK) - Partial cleanup:
```json
{
  "message": "Organization deleted successfully",
  "cleanup_status": {
    "vdb_deleted": false,
    "folders_archived": true,
    "organization_deleted": true,
    "errors": [
      "VDB deletion failed: Connection refused"
    ]
  }
}
```

**Error Responses**:

**404 Not Found**:
```json
{
  "message": "Not found"
}
```

**500 Internal Server Error**:
```json
{
  "error": "Failed to delete organization: <error_message>"
}
```

**What Happens**:
1. Retrieves VDB configuration
2. Undeploys VDB from Teiid server
3. Deletes VDB file from filesystem
4. Archives customer folders (moves to archive directory)
5. Deletes VDB record from database
6. Deletes organization record
7. Records audit event

**Note**: The organization is deleted even if VDB cleanup or folder archiving fails. Errors are reported in the `cleanup_status.errors` array.

---

### 4. Retry VDB Provisioning

Retry VDB provisioning for an organization where initial provisioning failed.

**Endpoint**: `POST /api/admin/organizations/<org_id>/retry-provision`

**Request Headers**:
```
Content-Type: application/json
Cookie: session=<session_token>
```

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | integer | Organization ID |

**Response** (200 OK):
```json
{
  "folders_status": {
    "created": true,
    "vdb_folder": "/opt/wildfly/teiidfiles/customers/1/vdb",
    "uploads_folder": "/opt/wildfly/teiidfiles/customers/1/uploads",
    "error": null
  },
  "vdb_status": {
    "provisioned": true,
    "vdb_id": "vdb_development",
    "status": "active",
    "error": null
  }
}
```

**Error Responses**:

**400 Bad Request** - VDB already exists:
```json
{
  "error": "Organization already has an active VDB",
  "vdb_id": "vdb_development"
}
```

**404 Not Found**:
```json
{
  "message": "Not found"
}
```

**500 Internal Server Error** - Provisioning failed:
```json
{
  "folders_status": {
    "created": true,
    "vdb_folder": "/opt/wildfly/teiidfiles/customers/1/vdb",
    "uploads_folder": "/opt/wildfly/teiidfiles/customers/1/uploads",
    "error": null
  },
  "vdb_status": {
    "provisioned": false,
    "error": "Template VDB not found"
  }
}
```

**What Happens**:
1. Checks if VDB already exists and is active
2. Creates/verifies customer folder structure
3. Provisions VDB from template
4. Generates new credentials
5. Deploys VDB to Teiid server
6. Records audit event

**Use Cases**:
- Initial VDB provisioning failed due to temporary issues
- Teiid server was down during organization creation
- Template VDB was missing but is now available
- Customer folders were deleted and need to be recreated

---

## Integration with React UI

The React admin UI (`app/pages/admin/VDBManagement.jsx`) uses these endpoints:

### Create Organization Flow
```javascript
// User clicks "Create Organization" in UI
const response = await $http.post('/api/admin/organizations', {
  name: 'New Organization',
  slug: 'new-org',
  provision_vdb: true
});

// UI displays:
// - Organization created successfully
// - VDB provisioning status
// - Folder creation status
```

### Get Organization Details
```javascript
// Load organization list with VDB status
const orgs = await $http.get('/api/organizations');

// For each org, get VDB details
for (const org of orgs.data) {
  try {
    const vdb = await $http.get(`/api/organizations/${org.id}/vdb`);
    org.vdb = vdb.data;
    org.hasVDB = true;
  } catch (error) {
    org.hasVDB = false;
  }
}
```

### Delete Organization
```javascript
// User clicks delete button
Modal.confirm({
  title: 'Delete Organization',
  content: 'Are you sure?',
  onOk: async () => {
    await $http.delete(`/api/admin/organizations/${orgId}`);
    notification.success('Organization deleted');
  }
});
```

### Retry Provisioning
```javascript
// User clicks "Retry Provision" for failed org
const response = await $http.post(
  `/api/admin/organizations/${orgId}/retry-provision`
);

if (response.data.vdb_status.provisioned) {
  notification.success('VDB provisioned successfully');
} else {
  notification.error('Provisioning failed: ' + response.data.vdb_status.error);
}
```

---

## Error Handling

### Common Error Scenarios

**1. Slug Validation Errors**
- **Cause**: Invalid slug format
- **Response**: 400 Bad Request with specific validation message
- **UI Action**: Display error message, highlight slug field

**2. Duplicate Slug**
- **Cause**: Organization with same slug already exists
- **Response**: 400 Bad Request
- **UI Action**: Display error, suggest alternative slug

**3. VDB Provisioning Failure**
- **Cause**: Teiid server down, template missing, network issues
- **Response**: 201 Created (org created) with error in `vdb_status`
- **UI Action**: Show organization created, display VDB error, offer retry

**4. Folder Creation Failure**
- **Cause**: Permission issues, disk full, path doesn't exist
- **Response**: 201 Created with error in `folders_status`
- **UI Action**: Show organization created, display folder error

**5. Authorization Failure**
- **Cause**: User is not super admin
- **Response**: 403 Forbidden
- **UI Action**: Redirect to home or show access denied

---

## Security Considerations

### Access Control
- ✅ All endpoints require super admin role
- ✅ Session-based authentication
- ✅ CSRF protection enabled
- ✅ Audit logging for all operations

### Data Protection
- ✅ VDB credentials encrypted in database
- ✅ Credentials never returned in API responses
- ✅ Slug validation prevents injection attacks
- ✅ Organization isolation enforced

### Audit Trail
All operations are logged with:
- User ID and name
- Organization ID
- Action type (create, delete, retry_provision)
- Timestamp
- IP address
- User agent

---

## Testing

### Manual Testing with curl

**Create Organization**:
```bash
curl -X POST http://localhost:5000/api/admin/organizations \
  -H "Content-Type: application/json" \
  -H "Cookie: session=<your_session>" \
  -d '{
    "name": "Test Organization",
    "slug": "test-org",
    "provision_vdb": true
  }'
```

**Get Organization**:
```bash
curl -X GET http://localhost:5000/api/admin/organizations/1 \
  -H "Cookie: session=<your_session>"
```

**Delete Organization**:
```bash
curl -X DELETE http://localhost:5000/api/admin/organizations/1 \
  -H "Cookie: session=<your_session>"
```

**Retry Provisioning**:
```bash
curl -X POST http://localhost:5000/api/admin/organizations/1/retry-provision \
  -H "Content-Type: application/json" \
  -H "Cookie: session=<your_session>"
```

### Testing Checklist
- [ ] Create organization with valid slug
- [ ] Create organization with invalid slug (should fail)
- [ ] Create organization with duplicate slug (should fail)
- [ ] Create organization without VDB provisioning
- [ ] Get organization details with VDB
- [ ] Get organization details without VDB
- [ ] Delete organization with VDB
- [ ] Delete organization without VDB
- [ ] Retry provisioning for failed organization
- [ ] Retry provisioning for organization with active VDB (should fail)
- [ ] Test as non-admin user (should fail with 403)

---

## Dependencies

### Required Services
- **VDBManagementService**: For VDB provisioning and deletion
- **CustomerFolderService**: For folder creation and archiving
- **OrganizationVDB Model**: For VDB configuration storage

### Required Configuration
```bash
# .env or environment variables
VDB_MULTI_TENANCY_ENABLED=true
VDB_TEMPLATE_NAME=MyVDBTest
TEIID_SERVLET_URL=http://localhost:8080/TeiidExcelImporterTest
TEIID_SERVLET_API_KEY=<api_key>
VDB_SECRET_KEY=<encryption_key>
```

---

## Troubleshooting

### "Failed to create organization: OrganizationVDB not found"
- **Cause**: OrganizationVDB model not imported
- **Solution**: Ensure model is created and imported in `redash/models/__init__.py`

### "Failed to provision VDB: Template VDB not found"
- **Cause**: Template VDB file missing on Teiid server
- **Solution**: Ensure `/opt/wildfly/teiidfiles/MyVDBTest-vdb.xml` exists

### "Failed to create customer folders: Permission denied"
- **Cause**: Redash process doesn't have write permissions
- **Solution**: Check folder permissions: `chmod 755 /opt/wildfly/teiidfiles/customers`

### "403 Forbidden"
- **Cause**: User is not super admin
- **Solution**: Grant super admin role to user

---

## Future Enhancements

Planned features:
- [ ] Bulk organization creation
- [ ] Organization templates
- [ ] Scheduled VDB provisioning
- [ ] Organization cloning
- [ ] VDB migration between organizations
- [ ] Organization usage metrics

---

## Support

For issues or questions:
- Check Redash logs: `redash/logs/`
- Check Teiid logs: `/opt/wildfly/standalone/log/server.log`
- Review VDB Management documentation
- Contact system administrator
