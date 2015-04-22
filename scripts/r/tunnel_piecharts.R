##################################################
##                                              ##
## tunnel_piecharts.R                           ##
##                                              ##
##################################################
##                                              ##
## Create piecharts for profiling_*x*.log files ##
## in the same folder as this script.           ##
##                                              ##
## NOTE: This has to be run using source() and  ##
##       the scripts have to be in the same     ##
##       folder (or change intputPath).         ##
##                                              ##
##################################################

# [VARIABLE] Change the path where the input files are located
inputPath <- "."
if ("OVERRIDE_TUNNEL_PIECHARTS_INPUTPATH" %in% names(Sys.getenv())){
	inputPath <- Sys.getenv()["OVERRIDE_TUNNEL_PIECHARTS_INPUTPATH"]
}

# [FUNCTION] Strip unit from measurement (e.g. 3x becomes 3)
stripUnit <- function(t) { 
	s <- as.character(t)
	return (as.numeric(substr(s, 1, nchar(s)-1)))
}

# [FUNCTION] Strip file name from /fulldir/filename:linenum format
stripFileName <- function (f) {
	fileandline <- basename(as.character(f))
	filename <- unlist(strsplit(fileandline, ":"))[1]
	return (paste(filename, sep="", collapse="") )
}

# [FUNCTION] Clean up profiling data frames
sanitiseData <- function(data) {
	# Rename the columns
	colnames(data) <- c("amount", "time", "file", "name")
	# Remove human units
	data$amount <- lapply(data$amount, stripUnit)
	data$time <- lapply(data$time, stripUnit)
	# Remove directory name from file name
	data$file<- lapply(data$file, stripFileName)
	# Remove entries with a time of 0s
	data <- subset(data, time > 0)
	return (data)
}

# [FUNCTION] Try to read a file which was just created
nfread <- function(x, i) { 
tryCatch(
	{return(read.table(x))}, 
	error = function(e) { 
		if (i > 0) {
			Sys.sleep(0.5)
			return(nfread(x, i-1))
		} else {
			return(0)
		}
	})
}

# [MAIN] 
# Find all profiling output files
allfiles <- list.files(path=inputPath, pattern="profiling_[[:digit:]]x[[:digit:]].log")

# Prepare a drawing area, as square as possible
figcolumns <- floor(sqrt(length(allfiles)))

stopifnot(figcolumns > 0)

figrows <- ceiling(length(allfiles)/figcolumns)

pdf('profile_piechart.pdf', width=20, height=15)
par(xpd=TRUE, mfrow=c(figcolumns,figrows), mar=c(4,1,4,1))

# Loop through all the files and fill area with pie charts
for(i in 1:length(allfiles)) {
	# Read the data and clean it
	file <- allfiles [i]
	data <- nfread(file, 10)	# 5s timeout
	data <- sanitiseData(data)

	# Create the pie chart
	configname <- gsub("(profiling_)?(.log)?", "", file)
	pie(unlist(data$time), labels = data$name, main=paste(configname, "Configuration, relative time spent"), cex=0.75)
}

dev.off()
