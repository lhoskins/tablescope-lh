/* eslint-disable react/prop-types */
import React, { useEffect, useRef } from 'react';

export default function NewUserPage({ onBack }) {
  const container = useRef(null);

  useEffect(() => {
    const ng = window.angular;
    if (!ng || !container.current) return undefined;

    const injector = ng.element(document.body).injector();
    if (!injector) return undefined;

    const $compile = injector.get('$compile');
    const $rootScope = injector.get('$rootScope');
    const $route = injector.get('$route');
    const $location = injector.get('$location');

    const scoped = $rootScope.$new(true);
    
    // Simulate the route locals for new user page
    if ($route.current) {
      $route.current.locals = $route.current.locals || {};
      $route.current.locals.isNewUserPage = true;
    }

    
    // Use the Angular users list component
    const template = '<page-users-list on-error="handleError"></page-users-list>';
    
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
      // Clean up route locals
      if ($route.current && $route.current.locals) {
        delete $route.current.locals.isNewUserPage;
      }
      if (scoped) scoped.$destroy();
      if (el && el[0] && el[0].parentNode) el[0].parentNode.removeChild(el[0]);
    };
  }, [onBack]);

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
