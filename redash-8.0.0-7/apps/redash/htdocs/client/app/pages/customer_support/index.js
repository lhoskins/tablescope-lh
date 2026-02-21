import template from './customer_support.html';
import notification from '@/services/notification';

function CustomerSupportCtrl(Events, messages) {
  Events.record('view', 'page', 'customer_support');

  this.messages = messages;
}

export default function init(ngModule) {
  ngModule.component('customerSupport', {
    template,
    controller: CustomerSupportCtrl,
  });

  return {
    '/customer_support': {
      template: '<customer-support></customer-support>',
      title: 'Customer Support',
    },
  };
}

init.init = true;
