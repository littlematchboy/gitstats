$( document ).ready(function() {
	$('.nav').find('a').each(function(index) { if(window.location.pathname.split('/').pop() == $(this).attr('href')) { $(this).parent().addClass('active'); console.log(this); } });
});