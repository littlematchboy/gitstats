<?php
// Grab all files from the desired folder
define(SEPARATOR, '-')

$repo = basename($_GET['folder']);
$mode = basename($_GET['mode']);

$branch = isset($_GET['branch']) ? SEPARATOR . basename($_GET['branch']) : '';

$files = glob("$repo/$mode$branch/*");

$dirs = array_filter($files, 'is_dir');
array_multisort(
	array_map( 'filemtime', $dirs ),
	SORT_NUMERIC,
	SORT_DESC,
	$dirs
);

$goto = $dirs[0];

if (!$goto) {
	die("Not found!");
} else {
	header("Location: $goto");
}