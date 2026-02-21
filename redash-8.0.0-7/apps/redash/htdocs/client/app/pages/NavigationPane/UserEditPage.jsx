/* eslint-disable react/prop-types */
import React, { useEffect, useRef } from 'react';

export default function UserEditPage({ userId, onBack }) {
  const container = useRef(null);

  useEffect(() => {
    const ng = window.angular;
    if (!ng || !container.current) return undefined;

    const injector = ng.element(document.body).injector();
    if (!injector) return undefined;

    const $compile = injector.get('$compile');
    const $rootScope = injector.get('$rootScope');
    const $route = injector.get('$route');
    
    // Store original route params to restore later
    const originalParams = $route.current ? { ...$route.current.params } : {};
    
    // Set the userId in $route.current.params BEFORE creating the component
    // This is what UserProfile.jsx reads: $route.current.params.userId
    if (!$route.current) {
      $route.current = { params: {} };
    }
    if (!$route.current.params) {
      $route.current.params = {};
    }
    $route.current.params.userId = userId;

    const scoped = $rootScope.$new(true);
    
    // Use the Angular user profile component
    const template = '<page-user-profile on-error="handleError"></page-user-profile>';
    
    const el = $compile(template)(scoped);
    el.css({ 
      width: '100%', 
      height: '100%', 
      minWidth: 0, 
      flex: '1 1 auto',
      display: 'flex',
      flexDirection: 'column'
    });

    container.current.innerHTML = '';
    container.current.appendChild(el[0]);
    scoped.$applyAsync();

    return () => {
      // Restore original route params
      if ($route.current && $route.current.params) {
        $route.current.params = originalParams;
      }
      if (scoped) scoped.$destroy();
      if (el && el[0] && el[0].parentNode) el[0].parentNode.removeChild(el[0]);
    };
  }, [userId]);

  return (
    <div
      ref={container}
      style={{
        flex: '1 1 auto',
        minHeight: 0,
        overflow: 'auto',
        width: '100%',
        height: '100%',
      }}
    />
  );
}
