pdf(NULL)

if (!require(igraph)){
    install.packages('igraph', repos="http://cran.us.r-project.org")
}

new_trust_graph <- function() {
    raw_data <- read.csv("trust.csv", sep=",")
    mid_edges <- as.matrix(raw_data[, c("mid1", "mid2")])
    colnames(mid_edges) <- NULL

    net <- graph_from_edgelist(mid_edges, directed=F)
    E(net)$width <- 5*raw_data$trust/sum(raw_data$trust/length(raw_data$trust))
    return(simplify(net, edge.attr.comb="sum"))
}

get_live_edges <- function() {
    raw_data <- read.csv("live_edges.csv", sep=",", stringsAsFactors = FALSE)
    node_map <- split(raw_data, raw_data$mid0)
    for (name in names(node_map)) {
        live_edges <- node_map[[name]] # List of named (mid0..mid4) columns
        row_count <- length(live_edges$mid0)

        single_edge_count <- 0
        single_edges_list <- c()
        for (i in 1:row_count){
            live_edge <- c(live_edges$mid0[i],
                           live_edges$mid1[i],
                           live_edges$mid2[i],
                           live_edges$mid3[i],
                           live_edges$mid4[i])
            for (j in 2:length(live_edge)){
                if (!identical(live_edge[j], "")){
                    single_edges_list <- c(single_edges_list, live_edge[j-1])
                    single_edges_list <- c(single_edges_list, live_edge[j])
                    single_edge_count <- single_edge_count + 1
                }
            }
        }
        #node_map[[name]] <- matrix(single_edges_list, nrow=single_edge_count, ncol=2, byrow=TRUE)
        node_map[[name]] <- single_edges_list
    }
    return(node_map)
}

trust_graph <- new_trust_graph()
live_edges <- get_live_edges()

plot_count <- NROW(live_edges)
color_palette <- palette(rainbow(plot_count))
current_color <- 1

png(filename = "trust.png", width=1920, height=1080*plot_count)
par(mfrow=c(plot_count,1))

for (source_node in names(live_edges)){
    live_edge <- live_edges[[source_node]]
    # Add non-local peer vertices
    for (v in live_edge){
        if (is.na(v) || (v == "")){
            v <- "?"
        }
        if (!(v %in% V(trust_graph)$name)){
            print(paste("WARNING: ADDING EXTERNAL VERTEX", v))
            trust_graph <- trust_graph + vertex(v)
        }
    }
}

for (source_node in names(live_edges)){
    live_edge <- live_edges[[source_node]]
    print(paste("PROCESSING EDGE", paste(live_edge, collapse=" ")))

    E(trust_graph)$color <- "#CCCCCCCC"
    # Color the edges in the live_edge
    for (i in seq(1, length(live_edge), 2)){  
        if (!is.na(live_edge[i]) && !is.na(live_edge[i+1]) && live_edge[i] != "" && live_edge[i+1] != ""){
            if (are_adjacent(trust_graph, live_edge[i], live_edge[i+1])) {
                E(trust_graph)[get.edge.ids(trust_graph, c(live_edge[i], live_edge[i+1]), directed = FALSE)]$color <- color_palette[current_color]
            } else {
                print(paste("WARNING: COULD NOT FIND EDGE FOR",  live_edge[i], live_edge[i+1]))
                trust_graph <- trust_graph + edge(live_edge[i], live_edge[i+1], width = 2, color = color_palette[current_color])
            }
        }
    }

    # Color the vertices of the live_edge
    V(trust_graph)$color <- 'orange'
    for (id in live_edge){
        if (!is.na(id) && id != ""){
            V(trust_graph)[id]$color <- color_palette[current_color]
        }
    }
    current_color <- current_color + 1

    if ("?" %in% V(trust_graph)$name) {
        trust_graph <- trust_graph - "?"
    }
    
    plot(trust_graph, layout = layout.fruchterman.reingold(trust_graph, niter=10000))
}
dev.off()

