// Define the controller for file uploader
class FileUploaderCtrl {
  constructor($http) {
    this.$http = $http;
    this.uploadStatus = '';
    this.destinationPath = '/upload'; // Modify this with the actual destination path
  }

  // Function to upload file
  uploadFile() {
    const formData = new FormData();
    formData.append('file', this.selectedFile);

    // Send file and destination path to server
    this.$http.post(`https://ssl.amt.hopi.cloud:3000${this.destinationPath}`, formData, {
      transformRequest: angular.identity,
      headers: { 'Content-Type': undefined }
    }).then(
      response => {
        // Handle successful upload
        this.uploadStatus = 'File uploaded successfully.';
      },
      error => {
        // Handle upload error
        this.uploadStatus = 'Error uploading file.';
      }
    );
  }
}

FileUploaderCtrl.$inject = ['$http'];

// Define initialization function
export default function init(ngModule) {
  // Register the fileUploader component
  ngModule.component('fileUploader', {
    // Assign the template from myupload.html
    template: require('./myupload.html'), // Use webpack or similar tool for require support
    // Assign the FileUploaderCtrl as the controller
    controller: FileUploaderCtrl,
  });

  // Define the route configuration
  return {
    '/file_uploader': {
      // Specify the component to render for the route
      template: '<file-uploader></file-uploader>',
      // Set the title for the page
      title: 'File Upload',
    },
  };
}

// Set initialization flag
init.init = true;
