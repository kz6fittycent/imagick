<?php
// Functional check of imagick.so, run by smoke-test.sh with the nextcloud
// snap's own PHP. Prints one line per check and exits non-zero on any
// failure.

$failed = 0;
$check = function (string $name, callable $f) use (&$failed) {
	try {
		$result = $f();
		echo "ok    $name" . ($result === null ? '' : ": $result") . "\n";
	} catch (Throwable $e) {
		echo "FAIL  $name: " . $e->getMessage() . "\n";
		$failed++;
	}
};
$expect = function (bool $cond, string $msg) {
	if (!$cond) {
		throw new RuntimeException($msg);
	}
};
$roundtrip = function (string $format) {
	$i = new Imagick();
	$i->newImage(64, 64, 'red');
	$i->setImageFormat($format);
	$j = new Imagick();
	$j->readImageBlob($i->getImageBlob());
	return $j->getImageWidth() . 'x' . $j->getImageHeight();
};

$check('extension loaded', function () use ($expect) {
	$expect(extension_loaded('imagick'), 'imagick is not loaded');
	$v = phpversion('imagick');
	$want = getenv('EXPECT_IMAGICK_VERSION');
	$expect(!$want || $v === $want, "phpversion('imagick') is $v, expected $want");
	return $v;
});
if (!extension_loaded('imagick')) {
	exit(1);
}

$check('ImageMagick version', function () use ($expect) {
	$v = Imagick::getVersion()['versionString'];
	$want = getenv('EXPECT_IM_VERSION');
	$expect(!$want || str_contains($v, "ImageMagick $want "), "expected $want");
	return $v;
});
$check('no OpenMP', function () use ($expect) {
	$features = Imagick::getConfigureOptions()['FEATURES'] ?? '';
	$expect(stripos($features, 'openmp') === false, "FEATURES: $features");
});
$check('formats', function () use ($expect) {
	$n = count(Imagick::queryFormats());
	$expect($n > 200, "only $n formats");
	foreach (['PNG', 'JPEG', 'WEBP', 'GIF', 'TIFF', 'SVG', 'HEIC', 'PDF', 'PS', 'PSD', 'TGA', 'SGI', 'TTF'] as $f) {
		$expect(in_array($f, Imagick::queryFormats(), true), "$f missing");
	}
	return $n;
});
$check('policy from the content tree', function () use ($expect) {
	$path = getenv('MAGICK_CONFIGURE_PATH');
	$expect($path && is_file("$path/policy.xml"), "MAGICK_CONFIGURE_PATH=$path");
	return $path;
});
foreach (['png', 'jpeg', 'webp', 'gif', 'tiff', 'heic'] as $format) {
	$check("$format write+read", fn () => $roundtrip($format));
}
$check('svg read (librsvg)', function () {
	$i = new Imagick();
	$i->readImageBlob('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><circle cx="16" cy="16" r="12" fill="red"/></svg>');
	$i->setImageFormat('png');
	$i->getImageBlob();
	return $i->getImageWidth() . 'x' . $i->getImageHeight();
});
$check('pdf write+read (ghostscript)', function () {
	$i = new Imagick();
	$i->newImage(100, 100, 'white');
	$i->setImageFormat('pdf');
	$j = new Imagick();
	$j->setResolution(72, 72);
	$j->readImageBlob($i->getImageBlob());
	$j->setImageFormat('png');
	$j->getImageBlob();
	return $j->getImageWidth() . 'x' . $j->getImageHeight();
});

exit($failed ? 1 : 0);
