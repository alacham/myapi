CREATE TABLE nodes (
  id              bigserial NOT NULL UNIQUE,
  name            varchar(255) UNIQUE, 
  internal_id     bigint DEFAULT NULL, 
  state           varchar(255) NOT NULL, 
  lastchange      timestamp NOT NULL,
  platform        varchar(255) DEFAULT 'nebula',
  PRIMARY KEY (id));

ALTER TABLE nodes
  ADD CONSTRAINT uq_nodes_iid_platform UNIQUE(internal_id, platform);

CREATE TABLE nebula_networks (
  id    	bigserial UNIQUE NOT NULL, 
  nebulaid 	bigint UNIQUE,
  size  	bigint,
  used  	bigint,
  vid   	bigint UNIQUE,
  type  	varchar(255), 
  shaping    	varchar(255) DEFAULT 'none|none|none|none',
--  platform 	varchar(255) DEFAULT 'nebula',
  reservedsince timestamp,
  startmac	macaddr DEFAULT NULL,
  PRIMARY KEY (id));


CREATE TABLE nebula_interfaces (
  id            bigserial NOT NULL, 
  node_id 	bigint NOT NULL REFERENCES nodes(id) ON DELETE CASCADE, 
  mac_addr      macaddr, 
  ip_addr       inet, 
  net_id        bigint NOT NULL REFERENCES nebula_networks(id),
  shaping       varchar(255) DEFAULT 'none|none|none|none', 
  PRIMARY KEY (id));
  

CREATE TABLE tagwords (
    id      bigserial UNIQUE NOT NULL, 
    tag     varchar(255) NOT NULL UNIQUE,
    parent  bigint REFERENCES tagwords(id) DEFAULT NULL,
    PRIMARY KEY (id));
  
CREATE TABLE numbered_names (
    id    bigserial NOT NULL, 
    tag   varchar(255) NOT NULL UNIQUE,
    seq   bigint NOT NULL,
  PRIMARY KEY (id));

CREATE TABLE node_taggings (
  node_id   bigint not null REFERENCES nodes(id) ON DELETE CASCADE,
  tag_id  bigint not null REFERENCES tagwords(id),
  PRIMARY KEY (node_id, tag_id)
);

CREATE TABLE net_taggings (
  net_id   bigint not null REFERENCES nebula_networks(id) ON DELETE CASCADE,
  tag_id  bigint not null REFERENCES tagwords(id),
  PRIMARY KEY (net_id, tag_id)
);

CREATE TABLE users (
  id		bigserial UNIQUE NOT NULL,
  name		varchar(255) UNIQUE NOT NULL,
  password	varchar(255) NOT NULL,
  salt		varchar(255) NOT NULL,
  isadmin	bool DEFAULT FALSE,
  kypouser	varchar(255),
  PRIMARY KEY (id));

CREATE TABLE templates (
  id           bigserial UNIQUE NOT NULL, 
  name         varchar(255) UNIQUE NOT NULL,
  template     text   NOT NULL,
  defaultvalues text,
  defaultuse   bool,
  userid       bigint REFERENCES users(id),
  platform     varchar(255) DEFAULT 'nebula',
  PRIMARY KEY (id));
 


-- http://www.postgresql.org/docs/8.4/static/sql-update.html RETURNING


CREATE TABLE virt_links (
  id    	bigserial UNIQUE NOT NULL, 
  intf1		bigint REFERENCES nebula_interfaces(id),
  intf2		bigint REFERENCES nebula_interfaces(id),
  bridgenode	bigint REFERENCES nodes(id),
  PRIMARY KEY (id));

CREATE TABLE vlink_taggings (
  link_id   bigint not null REFERENCES virt_links(id) ON DELETE CASCADE,
  tag_id  bigint not null REFERENCES tagwords(id),
  PRIMARY KEY (link_id, tag_id)
);
