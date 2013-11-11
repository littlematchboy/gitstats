<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>

	<meta http-equiv="content-type" content="text/html; charset=iso-8859-1"/>
	<title>Sidebar</title>

	<link rel="stylesheet" href="/assets/treeview/jquery.treeview.css" />
	<link rel="stylesheet" href="/assets/treeview/screen.css" />

	<script src="https://ajax.googleapis.com/ajax/libs/jquery/1.7/jquery.min.js"></script>
	<script src="/assets/js/jquery.cookie.js"></script>
	<script src="/assets/treeview/jquery.treeview.js"></script>
	</head>
	<body>
	
	<h2>GitStats</h2> &copy; TradeHero 2013<br/><br/>
	<ul id="browser" class="filetree">

		<?php
			$dirs = array_filter(glob('*'), 'is_dir');
			foreach ($dirs as $dir) {
				if ($dir == "assets") continue;
		?>
		<li class="closed"><span class="folder"><?=$dir ?></span>
			<ul>
				<li><a href="<?=$dir ?>/all" target="_main" class="file">All-time</a></li>
				<li><a href="latest.php?folder=<?=$dir ?>&mode=weekly" target="_main" class="file">Weekly</a></li>
				<li><a href="latest.php?folder=<?=$dir ?>&mode=monthly" target="_main" class="file">Monthly</a></li>
				<li><a href="latest.php?folder=<?=$dir ?>&mode=quarterly" target="_main" class="file">Quarterly</a></li>
				<li>
					<span class="folder"><a href="<?=$dir ?>" target="_main">Archive records</a></span>
				</li>
			</ul>
		</li>
		
		<?php
			}
		?>
	</ul>
	
	<script type="text/javascript">
	$(document).ready(function(){

		// first example
		$("#browser").treeview();
	});
	</script>

</body>
</html>