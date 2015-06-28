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

# [FUNCTION] Get the top n results and group the rest (length = n+1)
topData <- function(data, n) {
	# Order descending on time
	data <- data[order(-unlist(data$time)),]
	# If the length of the data frame is larger than n, compress it
	len <- length(data$time)
	if (len > n){
		others <- tail(data, len - n)	
		data <- head(data, n)

		insert <- data.frame(amount = sum(unlist(others$amount)),
						time = sum(unlist(others$time)),
						file = "N/A",
						name = "remainder")
		
		data <- rbind(data, insert)
	}
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

# [MAIN] PIECHARTS

pdf('profile_piechart.pdf', width=15, height=6)
par(xpd=TRUE, mfrow=c(figcolumns,figrows), mar=c(0,4,1,2))

# Loop through all the files and fill area with pie charts
for(i in 1:length(allfiles)) {
	# Read the data and clean it
	file <- allfiles [i]
	data <- nfread(file, 10)	# 5s timeout
	data <- sanitiseData(data)
	data <- topData(data, 10)

	# Create the pie chart
	if (length(data$time) > 0){
		configname <- gsub("(profiling_)?(.log)?", "", file)
		pie(unlist(data$time), labels = data$name, main=paste(configname, "Configuration, relative time spent"), radius = 0.6, cex=1)
	} else {
		frame()
	}
}

dev.off()

# [MAIN] HISTOGRAMS

pdf('profile_histogram.pdf', width=15, height=20)
par(xpd=TRUE, mfrow=c(figcolumns,figrows), mar=c(21,4,1,1))

# Loop through all the files and fill area with histograms
for(i in 1:length(allfiles)) {
	# Read the data and clean it
	file <- allfiles [i]
	data <- nfread(file, 10)	# 5s timeout
	data <- sanitiseData(data)
	data <- topData(data, 20)

	# Create the histogram
	if (length(data$time) > 0){
		configname <- gsub("(profiling_)?(.log)?", "", file)
		barplot(unlist(data$time), ylab="time (s)", names.arg=unlist(data$name), main=paste(configname, "Configuration, absolute time spent"), las=2)
	} else {
		frame()
	}
}

dev.off()
