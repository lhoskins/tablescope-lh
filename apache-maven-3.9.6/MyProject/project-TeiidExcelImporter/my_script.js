function sendExcelData(excelData) {
  $.ajax({
    url: "http://64.52.108.62:3001/uploadExcelFile", // Replace with your actual server-side script URL
    type: "POST",
    data: excelData,
    processData: false,
    contentType: false,
    success: function(response) {
      $("#message").text(response);
    },
    error: function(jqXHR, textStatus, errorThrown) {
      $("#message").text("Error uploading file: " + errorThrown);
    }
  });
}
