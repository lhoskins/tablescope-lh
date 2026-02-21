import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import { currentUser } from '@/services/auth';

/**
 * PermissionGuard Component
 * 
 * Conditionally renders children based on user permissions.
 * Checks permissions either from cached user permissions or via API call.
 * 
 * @param {string} permission - The permission to check (e.g., 'edit_query', 'delete_datasource')
 * @param {object} resource - Optional resource object with type and id for resource-specific checks
 * @param {React.ReactNode} children - Content to render if permission is granted
 * @param {React.ReactNode} fallback - Optional content to render if permission is denied
 */
export function PermissionGuard({ permission, resource, children, fallback = null }) {
  const [hasPermission, setHasPermission] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    checkPermission();
  }, [permission, resource]);

  const checkPermission = async () => {
    setIsLoading(true);

    try {
      // For simple permissions without a resource, just check locally
      if (!resource) {
        const hasLocalPermission = currentUser.hasPermission && currentUser.hasPermission(permission);
        setHasPermission(hasLocalPermission);
        setIsLoading(false);
        return;
      }

      // For resource-specific permissions, use the API
      const payload = {
        permission,
        resource_type: resource.type,
        resource_id: resource.id,
      };

      const response = await fetch('api/permissions/check', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`Permission check failed: ${response.statusText}`);
      }

      const data = await response.json();
      setHasPermission(data.has_permission);
    } catch (error) {
      // On error, deny permission by default
      console.error('Permission check failed:', error);
      setHasPermission(false);
    } finally {
      setIsLoading(false);
    }
  };

  // While loading, render a loading indicator if children would be visible
  if (isLoading) {
    // Return null to avoid flickering, but log for debugging
    console.debug('PermissionGuard: checking permission', permission, resource);
    return null;
  }

  // If permission denied, render fallback or null
  if (!hasPermission) {
    console.debug('PermissionGuard: permission denied', permission, resource);
    return fallback;
  }

  // Permission granted, render children
  console.debug('PermissionGuard: permission granted', permission, resource);
  return <>{children}</>;
}

PermissionGuard.propTypes = {
  permission: PropTypes.string.isRequired,
  resource: PropTypes.shape({
    type: PropTypes.string.isRequired,
    id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  }),
  children: PropTypes.node.isRequired,
  fallback: PropTypes.node,
};

PermissionGuard.defaultProps = {
  resource: null,
  fallback: null,
};

export default PermissionGuard;
