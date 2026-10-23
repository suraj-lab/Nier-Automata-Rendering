-- Monitors
hl.monitor({
	output = "DP-2",
	mode = "3440x1440@164.90",
	position = "1920x-400",
	scale = 1,
	vrr = 2,
	bitdepth = 10,
	cm = "hdr",
	sdrbrightness = 1.0,
	sdrsaturation = 1.0,
})
hl.monitor({
	output = "desc:ViewSonic Corporation VX2476 Series UPA213310203",
	mode = "1920x1080@74",
	position = "0x0",
	scale = 1,
})
hl.monitor({ output = "DP-4", disabled = true })
hl.monitor({ output = "DP-5", disabled = true })
